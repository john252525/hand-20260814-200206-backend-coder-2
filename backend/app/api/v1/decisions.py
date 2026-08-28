from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import Decision, Tender, CommercialOffer, Supplier, Task
from app.services.decision_service import create_decision, get_auto_recommendation
from app.services.risk_service import evaluate_risks
from app.services.settings_service import get_section
from app.services.tender_status_service import change_tender_status
from app.services.webhook_integration import notify_decision_made

# ... (остальные импорты и схемы)

@router.post("/{tender_id}/approve")
async def approve(tender_id: UUID, payload: ApprovePayload, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id, options=[selectinload(Tender.positions)])
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})
    if tender.status != "READY_FOR_DECISION":
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "Tender is not ready for decision"})
    supplier = await db.get(Supplier, payload.chosen_supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Supplier not found"})
    offer = await db.get(CommercialOffer, payload.chosen_offer_id, options=[selectinload(CommercialOffer.lot_supplier)])
    if not offer or offer.tender_id != tender_id or offer.lot_supplier.supplier_id != supplier.id:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "Offer does not match supplier/tender"})
    decision = await create_decision(db, tender, "APPROVED", payload.comment, chosen_supplier_id=supplier.id, chosen_offer_id=offer.id, tender_positions=tender.positions)
    await change_tender_status(db, tender, "APPROVED", note=f"Одобрено. Причина: {payload.comment}")
    await db.commit()
    await notify_decision_made(db, tender_id, "APPROVED")
    return {"success": True, "data": {"tender_id": tender_id, "decision": decision.decision}}

@router.post("/{tender_id}/reject")
async def reject(tender_id: UUID, payload: RejectPayload, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id, options=[selectinload(Tender.positions)])
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})
    if tender.status != "READY_FOR_DECISION":
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "Tender is not ready for decision"})
    decision = await create_decision(db, tender, "REJECTED", payload.comment or payload.reason, tender_positions=tender.positions)
    await change_tender_status(db, tender, "REJECTED", note=f"Отклонено. Причина: {payload.comment or payload.reason}")
    await db.commit()
    await notify_decision_made(db, tender_id, "REJECTED")
    return {"success": True, "data": {"tender_id": tender_id, "decision": decision.decision}}
