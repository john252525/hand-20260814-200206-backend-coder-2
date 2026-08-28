from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models import CommercialOffer, LotSupplier, Tender, Task
from app.services.negotiation_service import request_clarification, request_discount

router = APIRouter()

class NegotiatePayload(BaseModel):
    action: str = "request_clarification"
    target_supplier_ids: list[UUID] = []
    custom_instructions: Optional[str] = None

async def _get_competitive_prices(db: AsyncSession, tender_id: UUID, except_offer_id: UUID) -> dict:
    offers_result = await db.execute(
        select(CommercialOffer)
        .where(CommercialOffer.tender_id == tender_id, CommercialOffer.id != except_offer_id)
        .options(selectinload(CommercialOffer.positions))
    )
    competitive = {}
    for offer in offers_result.scalars().all():
        for pos in offer.positions:
            if pos.tender_position_id and pos.price_per_unit:
                current = competitive.get(pos.tender_position_id)
                if current is None or pos.price_per_unit < current:
                    competitive[pos.tender_position_id] = pos.price_per_unit
    return competitive

@router.post("/{tender_id}/negotiate", status_code=202)
async def negotiate(
    tender_id: UUID,
    payload: NegotiatePayload,
    db: AsyncSession = Depends(get_db),
):
    if payload.action not in ("request_clarification", "request_discount"):
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "action must be 'request_clarification' or 'request_discount'"})
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})
    query = select(LotSupplier).where(LotSupplier.tender_id == tender_id, LotSupplier.status.notin_(["DECLINED", "NO_RESPONSE"]))
    if payload.target_supplier_ids:
        query = query.where(LotSupplier.supplier_id.in_(payload.target_supplier_ids))
    result = await db.execute(query)
    lot_suppliers = result.scalars().all()
    processed = 0
    for ls in lot_suppliers:
        if payload.action == "request_clarification":
            offers = await db.execute(
                select(CommercialOffer)
                .where(CommercialOffer.lot_supplier_id == ls.id, CommercialOffer.clarification_needed == True)
                .options(selectinload(CommercialOffer.positions))
            )
        else:
            offers = await db.execute(
                select(CommercialOffer)
                .where(CommercialOffer.lot_supplier_id == ls.id, CommercialOffer.clarification_needed == False, CommercialOffer.status == "FULL")
                .options(selectinload(CommercialOffer.positions))
            )
        offer = offers.scalars().first()
        if not offer:
            continue
        if payload.action == "request_clarification":
            await request_clarification(db, ls, offer, payload.custom_instructions)
            processed += 1
        elif payload.action == "request_discount":
            competitive = await _get_competitive_prices(db, tender_id, offer.id)
            if competitive:
                await request_discount(db, ls, offer, competitive, payload.custom_instructions)
                processed += 1
    await db.commit()
    return {"success": True, "data": {"processed": processed, "status": "ACCEPTED"}}

@router.get("/{tender_id}/negotiation-status")
async def negotiation_status(tender_id: UUID, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})
    result = await db.execute(
        select(LotSupplier)
        .where(LotSupplier.tender_id == tender_id)
        .options(
            selectinload(LotSupplier.supplier),
            selectinload(LotSupplier.commercial_offers),
        )
    )
    lot_suppliers = result.scalars().all()
    statuses = [ls.status for ls in lot_suppliers]
    if any(s == "NEGOTIATING" for s in statuses):
        result_status = "IN_PROGRESS"
    elif any(s in ("CP_REQUESTED", "CP_PARTIALLY_RECEIVED", "CP_FULLY_RECEIVED", "RESPONDED") for s in statuses):
        result_status = "NOT_STARTED"
    else:
        result_status = "COMPLETED"
    suppliers_info = []
    for ls in lot_suppliers:
        offers = list(ls.commercial_offers)
        offers.sort(key=lambda o: o.created_at)  # первая версия КП
        best_margin = None
        initial_margin = None
        last_action = None
        if offers:
            margins = [o.margin_percent for o in offers if o.margin_percent is not None]
            if margins:
                best_margin = max(margins)
                initial_margin = margins[0]
        suppliers_info.append({
            "supplier_id": ls.supplier_id,
            "supplier_name": ls.supplier.name if ls.supplier else None,
            "initial_margin_percent": initial_margin,
            "current_margin_percent": best_margin,
            "improvement_percent": (best_margin - initial_margin) if (best_margin is not None and initial_margin is not None) else None,
            "status": ls.status,
            "last_action": last_action,
            "last_action_at": None,
        })
    return {
        "success": True,
        "data": {
            "status": result_status,
            "cycles_completed": 0,  # TODO: реализовать подсчёт циклов в отдельной таблице
            "max_cycles": 2,
            "started_at": None,
            "suppliers": suppliers_info,
        },
    }
