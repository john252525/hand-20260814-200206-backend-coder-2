import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models import CommercialOffer, Task, Tender
from app.services.cp_parser import parse_cp_text, save_parsed_cp
from app.workers.celery_app import celery_app


@celery_app.task(name="parse_cp", bind=True)
def parse_cp_task(self, offer_id: str, task_id: str | None = None) -> dict:
    try:
        asyncio.run(_parse_cp(offer_id, task_id))
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


async def _parse_cp(offer_id: str, task_id: str | None = None):
    if task_id:
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "IN_PROGRESS"
                await db.commit()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CommercialOffer)
            .where(CommercialOffer.id == UUID(offer_id))
            .options(selectinload(CommercialOffer.positions))
        )
        offer = result.scalar_one_or_none()
        if not offer:
            return

        tender = await db.get(
            Tender,
            offer.tender_id,
            options=[selectinload(Tender.positions)],
        )
        if not tender:
            return

        cp_text = offer.raw_text_snippet or ""
        parsed, _ = await parse_cp_text(db, tender, cp_text)
        await save_parsed_cp(db, offer, parsed, tender)
        await db.commit()

        if task_id:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "COMPLETED"
                task.output_data = {"status": offer.status, "coverage": offer.coverage}
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()
