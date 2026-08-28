from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tender, TenderStatusHistory
from app.services.webhook_integration import notify_tender_ready_for_decision


async def change_tender_status(
    db: AsyncSession,
    tender: Tender,
    new_status: str,
    note: str = "",
) -> None:
    """Единая точка смены статуса тендера с записью истории."""
    if tender.status == new_status:
        return
    db.add(
        TenderStatusHistory(
            tender_id=tender.id,
            status=new_status,
            previous_status=tender.status,
            note=note,
        )
    )
    tender.status = new_status
    await db.flush()
    if new_status == "READY_FOR_DECISION":
        # Уведомляем без передачи db, чтобы не делать дополнительный commit в текущей сессии
        await notify_tender_ready_for_decision(tender.id)
