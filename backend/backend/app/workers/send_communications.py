import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models import LotSupplier, Supplier, Tender, Task
from app.services.communication_service import send_cp_request_to_supplier
from app.workers.celery_app import celery_app


@celery_app.task(name="send_cp_requests", bind=True)
def send_cp_requests(self, tender_id: str, task_id: str | None = None, supplier_ids: list[str] | None = None) -> dict:
    try:
        asyncio.run(_send_cp_requests(tender_id, task_id, supplier_ids))
        return {"status": "completed"}
    except Exception as e:
        if task_id:
            asyncio.run(_update_task_error(task_id, str(e)))
        raise


async def _update_task_error(task_id: str, error: str):
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        if task:
            task.status = "FAILED"
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()


async def _send_cp_requests(tender_id: str, task_id: str | None = None, supplier_ids: list[str] | None = None):
    if task_id:
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "IN_PROGRESS"
                await db.commit()

    async with AsyncSessionLocal() as db:
        tender = await db.get(Tender, UUID(tender_id), options=[selectinload(Tender.positions)])
        if not tender:
            return

        query = select(LotSupplier).where(LotSupplier.tender_id == tender.id, LotSupplier.status != "DECLINED")
        if supplier_ids:
            query = query.where(LotSupplier.supplier_id.in_([UUID(s) for s in supplier_ids]))
        result = await db.execute(query)
        lot_suppliers = result.scalars().all()

        sent_count = 0
        for ls in lot_suppliers:
            supplier = await db.get(Supplier, ls.supplier_id)
            if supplier and supplier.email:
                await send_cp_request_to_supplier(db, tender, supplier, ls)
                sent_count += 1
        await db.commit()

        if task_id:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "COMPLETED"
                task.output_data = {"sent": sent_count}
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()
