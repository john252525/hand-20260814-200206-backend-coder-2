import asyncio
import os
import structlog
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import (
    CommercialOffer,
    Communication,
    CommunicationAttachment,
    LotSupplier,
    Supplier,
    Task,
    Tender,
)
from app.services.tender_status_service import change_tender_status
from app.services.email_classifier import classify_email
from app.workers.celery_app import celery_app
from app.workers.parse_cp import parse_cp_task
from app.services.webhook_integration import notify_cp_received

logger = structlog.get_logger(__name__)

@celery_app.task(name="process_incoming_email", bind=True)
def process_incoming_email_task(self, email_data: dict) -> dict:
    try:
        asyncio.run(_process_incoming_email(email_data))
        return {"status": "completed"}
    except Exception as e:
        logger.error("process_incoming.failed", error=str(e))
        raise self.retry(exc=e, countdown=60)

async def _process_incoming_email(email_data: dict):
    async with AsyncSessionLocal() as db:
        from_ = email_data.get("from_", "")
        subject = email_data.get("subject", "")
        body = email_data.get("body", "")
        message_id = email_data.get("message_id", "")
        in_reply_to = email_data.get("in_reply_to", "")
        if message_id:
            existing = await db.execute(
                select(Communication).where(Communication.external_id == message_id)
            )
            if existing.scalar_one_or_none():
                return
        email_clean = from_.split("<")[-1].split(">")[0].strip() if "<" in from_ else from_.strip()
        result = await db.execute(select(Supplier).where(Supplier.email.ilike(f"%{email_clean}%")))
        supplier = result.scalar_one_or_none()
        if not supplier:
            return
        lot_supplier = None
        if in_reply_to:
            outbound = await db.execute(
                select(Communication).where(
                    Communication.external_id == in_reply_to,
                    Communication.direction == "outgoing",
                )
            )
            outbound_comm = outbound.scalar_one_or_none()
            if outbound_comm:
                lot_supplier = await db.get(LotSupplier, outbound_comm.lot_supplier_id)
                if lot_supplier and lot_supplier.supplier_id != supplier.id:
                    lot_supplier = None
        if not lot_supplier:
            result = await db.execute(
                select(LotSupplier)
                .where(LotSupplier.supplier_id == supplier.id, LotSupplier.status != "DECLINED")
                .order_by(LotSupplier.created_at.desc())
            )
            lot_supplier = result.scalars().first()
        if not lot_supplier:
            return
        message_type = await classify_email(subject, body)
        if message_type == "decline":
            lot_supplier.status = "DECLINED"
            comm = Communication(
                lot_supplier_id=lot_supplier.id,
                tender_id=lot_supplier.tender_id,
                direction="incoming",
                channel="email",
                subject=subject,
                body_text=body,
                message_type="decline",
                external_id=message_id,
                received_at=datetime.now(timezone.utc),
            )
            db.add(comm)
            await db.flush()
            active_ls = await db.execute(
                select(LotSupplier).where(
                    LotSupplier.tender_id == lot_supplier.tender_id,
                    LotSupplier.status.notin_(["DECLINED", "NO_RESPONSE"]),
                )
            )
            if not active_ls.scalars().first():
                tender = await db.get(Tender, lot_supplier.tender_id)
                if tender:
                    await change_tender_status(db, tender, "NO_SUPPLIERS_FOUND", note="Все поставщики отказались")
            await db.commit()
            logger.info("process_incoming.declined", lot_supplier_id=str(lot_supplier.id), tender_id=str(lot_supplier.tender_id))
            return
        comm = Communication(
            lot_supplier_id=lot_supplier.id,
            tender_id=lot_supplier.tender_id,
            direction="incoming",
            channel="email",
            subject=subject,
            body_text=body,
            message_type=message_type,
            external_id=message_id,
            received_at=datetime.now(timezone.utc),
        )
        db.add(comm)
        await db.flush()
        for path in email_data.get("attachments", []):
            filename = path.split("/")[-1]
            db.add(CommunicationAttachment(
                communication_id=comm.id,
                filename=filename,
                file_size_bytes=os.path.getsize(path) if os.path.exists(path) else 0,
                storage_path=path,
            ))
        offer_id = None
        if message_type == "cp_response":
            offer = CommercialOffer(
                lot_supplier_id=lot_supplier.id,
                tender_id=lot_supplier.tender_id,
                source_communication_id=comm.id,
                status="PROCESSING",
                raw_text_snippet=body[:2000],
            )
            db.add(offer)
            await db.flush()
            offer_id = offer.id
            lot_supplier.status = "RESPONDED"
            task = Task(
                task_type="PARSE_CP",
                status="PENDING",
                entity_type="commercial_offer",
                entity_id=offer.id,
            )
            db.add(task)
            await db.flush()
            celery_task = parse_cp_task.delay(str(offer.id), str(task.id))
            task.celery_task_id = celery_task.id
        await db.commit()
        if offer_id:
            logger.info("process_incoming.cp_received", offer_id=str(offer_id), tender_id=str(lot_supplier.tender_id))
            await notify_cp_received(offer_id, lot_supplier.tender_id)
