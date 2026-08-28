import asyncio
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import AsyncSessionLocal
from app.models import Tender, Task
from app.services.supplier_search_service import search_suppliers_combined
from app.workers.celery_app import celery_app


@celery_app.task(name="search_suppliers", bind=True)
def search_suppliers_task(self, tender_id: str, task_id: str | None = None, options: dict | None = None) -> dict:
    try:
        asyncio.run(_search(tender_id, task_id, options or {}))
        return {"status": "completed"}
    except Exception as e:
        if task_id:
            asyncio.run(_update_task_error(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)


async def _update_task_error(task_id: str, error: str):
    from datetime import datetime, timezone
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        if task:
            task.status = "FAILED"
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()


async def _search(tender_id: str, task_id: str | None = None, options: dict | None = None):
    from datetime import datetime, timezone
    if task_id:
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "IN_PROGRESS"
                await db.commit()

    async with AsyncSessionLocal() as db:
        tender = await db.get(
            Tender,
            UUID(tender_id),
            options=[selectinload(Tender.positions)],
        )
        if not tender:
            return
        queries = [tender.title]
        if tender.positions:
            for pos in tender.positions[:3]:
                queries.append(f"{pos.name} оптом")
                queries.append(f"поставщик {pos.name}")
        results = []
        for q in queries:
            results.extend(await search_suppliers_combined(db, q, options.get("max_suppliers", 10)))
        # Дедупликация
        seen = set()
        unique = []
        for r in results:
            key = r.get("email") or r.get("website") or r.get("name")
            if key and key not in seen:
                seen.add(key)
                unique.append(r)

        task = await db.get(Task, UUID(task_id)) if task_id else None
        if task:
            task.status = "COMPLETED"
            task.output_data = {"queries": queries, "results": unique}
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()
