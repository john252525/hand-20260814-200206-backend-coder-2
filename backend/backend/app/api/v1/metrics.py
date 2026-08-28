from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models import Tender, Task, Communication, CommercialOffer

router = APIRouter()


@router.get("/metrics")
async def metrics():
    async with AsyncSessionLocal() as db:
        total_tenders = await db.scalar(select(func.count()).select_from(Tender)) or 0
        total_tasks = await db.scalar(select(func.count()).select_from(Task)) or 0
        failed_tasks = await db.scalar(select(func.count()).select_from(Task).where(Task.status == "FAILED")) or 0
        sent_comms = await db.scalar(select(func.count()).select_from(Communication).where(Communication.direction == "outgoing")) or 0
        received_comms = await db.scalar(select(func.count()).select_from(Communication).where(Communication.direction == "incoming")) or 0
        parsed_cp = await db.scalar(select(func.count()).select_from(CommercialOffer).where(CommercialOffer.status != "PROCESSING")) or 0

    content = f"""# HELP tenders_total Total tenders
# TYPE tenders_total gauge
tenders_total {total_tenders}
# HELP tasks_total Total tasks
# TYPE tasks_total gauge
tasks_total {total_tasks}
# HELP tasks_failed_total Failed tasks
# TYPE tasks_failed_total gauge
tasks_failed_total {failed_tasks}
# HELP communications_sent_total Sent communications
# TYPE communications_sent_total gauge
communications_sent_total {sent_comms}
# HELP communications_received_total Received communications
# TYPE communications_received_total gauge
communications_received_total {received_comms}
# HELP cp_parsed_total Parsed commercial offers
# TYPE cp_parsed_total gauge
cp_parsed_total {parsed_cp}
"""
    return Response(content=content, media_type="text/plain")
