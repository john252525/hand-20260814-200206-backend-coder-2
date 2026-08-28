import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tender, TenderStatusHistory

logger = structlog.get_logger(__name__)

async def change_tender_status(
    db: AsyncSession,
    tender: Tender,
    new_status: str,
    note: str = "",
) -> None:
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
    logger.info("tender.status_changed", tender_id=str(tender.id), previous_status=tender.status, new_status=new_status, note=note)
    tender.status = new_status
    await db.flush()
