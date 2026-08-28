import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models import Communication, LotSupplier

router = APIRouter()


class DirectionEnum(str, Enum):
    outgoing = "outgoing"
    incoming = "incoming"


class ChannelEnum(str, Enum):
    email = "email"
    telegram = "telegram"
    whatsapp = "whatsapp"
    web_form = "web_form"


class CommunicationCreate(BaseModel):
    lot_supplier_id: uuid.UUID
    direction: DirectionEnum = DirectionEnum.outgoing
    channel: ChannelEnum = ChannelEnum.email
    subject: str = ""
    body_text: str = ""
    message_type: str = "manual"


@router.post("", status_code=201)
async def create_communication(payload: CommunicationCreate, db: AsyncSession = Depends(get_db)):
    lot_supplier = await db.get(LotSupplier, payload.lot_supplier_id)
    if not lot_supplier:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "LotSupplier not found"})
    communication = Communication(
        lot_supplier_id=payload.lot_supplier_id,
        tender_id=lot_supplier.tender_id,
        direction=payload.direction.value,
        channel=payload.channel.value,
        subject=payload.subject,
        body_text=payload.body_text,
        message_type=payload.message_type,
        sent_at=datetime.now(timezone.utc) if payload.direction == DirectionEnum.outgoing else None,
    )
    db.add(communication)
    await db.commit()
    await db.refresh(communication)
    return {"success": True, "data": {"id": communication.id}}


@router.get("/by-tender/{tender_id}")
async def list_by_tender(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Communication).where(Communication.tender_id == tender_id).order_by(Communication.created_at.desc())
    )
    communications = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": c.id,
                "lot_supplier_id": c.lot_supplier_id,
                "direction": c.direction,
                "channel": c.channel,
                "subject": c.subject,
                "body_text": c.body_text[:500],
                "message_type": c.message_type,
                "sent_at": c.sent_at,
                "received_at": c.received_at,
            }
            for c in communications
        ],
    }
