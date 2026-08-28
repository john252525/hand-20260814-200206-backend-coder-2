import asyncio
import structlog
from datetime import datetime, timezone
import httpx
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource, Task
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

GOSPLAN_TEST_URL = "https://v2test.gosplan.info/fz44/purchases"

@celery_app.task(name="sync_tenders", bind=True)
def sync_tenders(self, source_id: str | None = None, task_id: str | None = None) -> dict:
    try:
        asyncio.run(_sync(source_id, task_id))
        return {"status": "completed"}
    except Exception as e:
        logger.error("sync_tenders.failed", error=str(e))
        if task_id:
            asyncio.run(_update_task_error(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)

async def _update_task_error(task_id: str, error: str):
    from uuid import UUID
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        if task:
            task.status = "FAILED"
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

async def _sync(source_id: str | None = None, task_id: str | None = None):
    if task_id:
        from uuid import UUID
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "IN_PROGRESS"
                await db.commit()

    async with AsyncSessionLocal() as db:
        if source_id:
            from uuid import UUID
            result = await db.execute(select(TenderSource).where(TenderSource.id == UUID(source_id)))
            source = result.scalar_one_or_none()
        else:
            result = await db.execute(select(TenderSource).where(TenderSource.is_active == True))
            source = result.scalars().first()
        if not source:
            logger.warning("sync_tenders.source_not_found", source_id=source_id)
            return

        url = source.api_url or settings.tender_source_api_url or GOSPLAN_TEST_URL
        params = {"limit": 50, "skip": 0, "published_after": "2024-01-01T00:00:00Z"}
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                items = resp.json()
            except Exception as e:
                source.last_sync_status = "error"
                source.last_error = str(e)
                await db.commit()
                logger.error("sync_tenders.source_error", source_id=source.id, error=str(e))
                if task_id:
                    await _update_task_error(task_id, str(e))
                return

        created = 0
        updated = 0
        for item in items:
            purchase_number = item.get("purchase_number", "")
            if not purchase_number:
                continue
            existing = await db.execute(
                select(Tender).where(Tender.source_id == source.id, Tender.source_tender_id == purchase_number)
            )
            existing_tender = existing.scalar_one_or_none()
            if existing_tender:
                existing_tender.title = item.get("object_info", existing_tender.title)
                existing_tender.description = item.get("object_info", existing_tender.description)
                existing_tender.nmck = item.get("max_price", existing_tender.nmck)
                existing_tender.deadline_at = item.get("collecting_finished_at") or item.get("submission_close_at") or existing_tender.deadline_at
                customers = item.get("customers") or []
                if customers:
                    existing_tender.customer_inn = str(customers[0])
                updated += 1
                continue
            customers = item.get("customers") or []
            customer_inn = str(customers[0]) if customers else ""
            tender = Tender(
                source_id=source.id,
                source_tender_id=purchase_number,
                title=item.get("object_info", "Без названия"),
                description=item.get("object_info", ""),
                nmck=item.get("max_price"),
                currency=item.get("currency_code", "RUB"),
                published_at=item.get("published_at"),
                deadline_at=item.get("collecting_finished_at") or item.get("submission_close_at"),
                customer_name=customer_inn,
                customer_inn=customer_inn,
                platform="ГосПлан",
                source_url=f"{url}/{purchase_number}",
                status="NEW",
            )
            db.add(tender)
            created += 1
        source.last_sync_at = datetime.now(timezone.utc)
        source.last_sync_status = "success"
        source.last_error = None
        await db.commit()
        logger.info("sync_tenders.completed", source_id=source.id, created=created, updated=updated)
        if task_id:
            from uuid import UUID
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "COMPLETED"
                task.output_data = {"created": created, "updated": updated}
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()
