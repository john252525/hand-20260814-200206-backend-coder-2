import asyncio
import structlog
from datetime import datetime, timezone
import httpx
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource, Task, TenderStatusHistory
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)
GOSPLAN_TEST_URL = 'https://v2test.gosplan.info/fz44/purchases'

@celery_app.task(name='sync_tenders', bind=True)
def sync_tenders(self, source_id: str | None = None, task_id: str | None = None) -> dict:
    try:
        asyncio.run(_sync(source_id, task_id))
        return {'status': 'completed'}
    except Exception as e:
        logger.error('sync_tenders.failed', error=str(e))
        if task_id:
            asyncio.run(_update_task_error(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)

async def _update_task_error(task_id: str, error: str):
    from uuid import UUID
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        if task:
            task.status = 'FAILED'
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

async def _sync(source_id: str | None = None, task_id: str | None = None):
    if task_id:
        from uuid import UUID
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = 'IN_PROGRESS'
                await db.commit()
    async with AsyncSessionLocal() as db:
        from uuid import UUID
        if source_id:
            result = await db.execute(select(TenderSource).where(TenderSource.id == UUID(source_id)))
            source = result.scalar_one_or_none()
        else:
            result = await db.execute(select(TenderSource).where(TenderSource.is_active == True))
            source = result.scalars().first()
        if not source:
            logger.warning('sync_tenders.source_not_found', source_id=source_id)
            return
        url = source.api_url or settings.tender_source_api_url or GOSPLAN_TEST_URL
        created, updated, found_ids = 0, 0, set()
        page_size = source.config.get('page_size', 50) if source.config else 50
        skip = 0
        while True:
            params = {'limit': page_size, 'skip': skip, 'published_after': '2024-01-01T00:00:00Z'}
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    items = resp.json()
            except Exception as e:
                source.last_sync_status = 'error'
                source.last_error = str(e)
                await db.commit()
                if task_id:
                    await _update_task_error(task_id, str(e))
                return
            if not items:
                break
            for item in items:
                purchase_number = item.get('purchase_number', '')
                if not purchase_number:
                    continue
                found_ids.add(purchase_number)
                existing = (await db.execute(
                    select(Tender).where(Tender.source_id == source.id, Tender.source_tender_id == purchase_number)
                )).scalar_one_or_none()
                if existing:
                    existing.title = item.get('object_info', existing.title)
                    existing.description = item.get('object_info', existing.description)
                    existing.nmck = item.get('max_price')
                    existing.deadline_at = item.get('collecting_finished_at') or item.get('submission_close_at') or existing.deadline_at
                    customers = item.get('customers') or []
                    if customers:
                        existing.customer_inn = str(customers[0])
                    existing.missing_count = 0
                    updated += 1
                    continue
                customers = item.get('customers') or []
                customer_inn = str(customers[0]) if customers else ''
                tender = Tender(
                    source_id=source.id,
                    source_tender_id=purchase_number,
                    title=item.get('object_info', 'Без названия'),
                    description=item.get('object_info', ''),
                    nmck=item.get('max_price'),
                    currency=item.get('currency_code', 'RUB'),
                    published_at=item.get('published_at'),
                    deadline_at=item.get('collecting_finished_at') or item.get('submission_close_at'),
                    customer_name=customer_inn,
                    customer_inn=customer_inn,
                    platform='ГосПлан',
                    source_url=f'{url}/{purchase_number}',
                    status='NEW',
                    missing_count=0,
                )
                db.add(tender)
                created += 1
            await db.flush()
            if len(items) < page_size:
                break
            skip += page_size
        # Архивация тендеров, отсутствующих в выдаче дважды
        all_source_tenders = (await db.execute(
            select(Tender).where(Tender.source_id == source.id)
        )).scalars().all()
        for t in all_source_tenders:
            if t.source_tender_id in found_ids:
                continue
            t.missing_count = (t.missing_count or 0) + 1
            if t.missing_count >= 2 and t.status not in ('APPROVED', 'REJECTED', 'ARCHIVED'):
                db.add(TenderStatusHistory(
                    tender_id=t.id, status='ARCHIVED', previous_status=t.status,
                    note='Тендер отсутствовал в выдаче источника 2 раза подряд',
                ))
                t.status = 'ARCHIVED'
        source.last_sync_at = datetime.now(timezone.utc)
        source.last_sync_status = 'success'
        source.last_error = None
        await db.commit()
        if task_id:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = 'COMPLETED'
                task.output_data = {'created': created, 'updated': updated}
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()
