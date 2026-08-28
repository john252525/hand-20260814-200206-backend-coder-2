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
from app.services.settings_service import get_section
from app.services.tender_status_service import change_tender_status
from app.services.webhook_integration import notify_decision_made

router = APIRouter()

class ApprovePayload(BaseModel):
    chosen_supplier_id: UUID
    chosen_offer_id: UUID
    comment: str = ""

class RejectPayload(BaseModel):
    reason: str = ""
    comment: str = ""

class RequestInfoPayload(BaseModel):
    instructions: str
    return_to_stage: str = "negotiation"

@router.get("")
async def list_decisions(
    status: Optional[str] = None,
    risk_level: Optional[str] = None,
    min_margin: Optional[float] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Tender).join(Decision).options(selectinload(Tender.decisions))
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        query = query.where(Tender.status.in_(statuses))
    if risk_level:
        levels = [r.strip() for r in risk_level.split(",") if r.strip()]
        query = query.where(Decision.risk_level_at_decision.in_(levels))
    if min_margin is not None:
        query = query.where(Decision.margin_at_decision >= min_margin)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Decision.decided_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    tenders = result.scalars().all()
    scoring_settings = await get_section(db, "scoring")
    data = []
    for t in tenders:
        dec = t.decisions
        if not dec:
            continue
        dec = dec[0] if isinstance(dec, list) else dec
        best_offer = dec.chosen_offer if dec.chosen_offer_id else None
        best_supplier = dec.chosen_supplier if dec.chosen_supplier_id else None
        data.append({
            "tender_id": t.id,
            "tender_title": t.title,
            "nmck": t.nmck,
            "deadline_at": t.deadline_at,
            "best_supplier": {
                "id": best_supplier.id if best_supplier else None,
                "name": best_supplier.name if best_supplier else None,
                "offer_id": dec.chosen_offer_id,
                "final_price": best_offer.total_cost_with_all if best_offer else None,
                "margin_percent": best_offer.margin_percent if best_offer else None,
            },
            "alternative_suppliers": [],
            "risk_assessment": {
                "level": dec.risk_level_at_decision,
                "factors": [],
            },
            "auto_recommendation": get_auto_recommendation(best_offer.margin_percent if best_offer else None, dec.risk_level_at_decision or "LOW", scoring_settings),
            "status": t.status,
            "ready_at": dec.decided_at,
        })
    return {
        "success": True,
        "data": data,
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }

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

@router.post("/{tender_id}/request-info", status_code=202)
async def request_info(tender_id: UUID, payload: RequestInfoPayload, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})
    from app.workers.process_tender import process_tender
    task = Task(
        task_type="PROCESS_TENDER",
        status="PENDING",
        entity_type="tender",
        entity_id=tender_id,
        input_data={"instructions": payload.instructions, "return_to_stage": payload.return_to_stage},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    celery_task = process_tender.delay(str(tender_id), str(task.id))
    task.celery_task_id = celery_task.id
    await db.commit()
    return {"success": True, "data": {"task_id": task.id, "status": "ACCEPTED", "check_url": f"/api/v1/tasks/{task.id}"}}
