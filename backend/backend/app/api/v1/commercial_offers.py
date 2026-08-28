import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import CommercialOffer, LotSupplier, Task

router = APIRouter()


@router.get("")
async def list_commercial_offers(
    tender_id: Optional[uuid.UUID] = None,
    supplier_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(CommercialOffer)
    if tender_id:
        query = query.where(CommercialOffer.tender_id == tender_id)
    if supplier_id:
        query = query.join(CommercialOffer.lot_supplier).where(LotSupplier.supplier_id == supplier_id)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        query = query.where(CommercialOffer.status.in_(statuses))

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(CommercialOffer.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    offers = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": o.id,
                "tender_id": o.tender_id,
                "lot_supplier_id": o.lot_supplier_id,
                "status": o.status,
                "coverage": o.coverage,
                "total_cost_with_all": o.total_cost_with_all,
                "margin_absolute": o.margin_absolute,
                "margin_percent": o.margin_percent,
                "created_at": o.created_at,
            }
            for o in offers
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }


@router.get("/{offer_id}")
async def get_commercial_offer(offer_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CommercialOffer)
        .where(CommercialOffer.id == offer_id)
        .options(selectinload(CommercialOffer.positions))
    )
    offer = result.scalar_one_or_none()
    if not offer:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Commercial offer not found"})
    return {
        "success": True,
        "data": {
            "id": offer.id,
            "tender_id": offer.tender_id,
            "lot_supplier_id": offer.lot_supplier_id,
            "status": offer.status,
            "coverage": offer.coverage,
            "clarification_needed": offer.clarification_needed,
            "clarification_items": offer.clarification_items,
            "positions": [
                {
                    "id": p.id,
                    "tender_position_id": p.tender_position_id,
                    "supplier_name": p.supplier_name,
                    "match_type": p.match_type,
                    "price_per_unit": p.price_per_unit,
                    "quantity_available": p.quantity_available,
                    "delivery_days": p.delivery_days,
                    "nds_included": p.nds_included,
                    "nds_rate": p.nds_rate,
                    "total_price": p.total_price,
                }
                for p in offer.positions
            ],
            "total_cost": offer.total_cost,
            "delivery_cost": offer.delivery_cost,
            "total_cost_with_delivery": offer.total_cost_with_delivery,
            "total_cost_with_all": offer.total_cost_with_all,
            "margin_absolute": offer.margin_absolute,
            "margin_percent": offer.margin_percent,
            "payment_terms": offer.payment_terms,
            "delivery_terms": offer.delivery_terms,
            "valid_until": offer.valid_until,
            "raw_text_snippet": offer.raw_text_snippet[:500],
            "parsed_at": offer.parsed_at,
        },
    }


@router.post("/{offer_id}/reparse", status_code=202)
async def reparse_offer(offer_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    offer = await db.get(CommercialOffer, offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Commercial offer not found"})

    # Проверяем, нет ли уже активной задачи на этот offer
    existing_task = await db.execute(
        select(Task).where(
            Task.entity_type == "commercial_offer",
            Task.entity_id == offer_id,
            Task.status.in_(["PENDING", "IN_PROGRESS"]),
        )
    )
    if existing_task.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "A reparse task is already in progress"})

    task = Task(
        task_type="PARSE_CP",
        status="PENDING",
        entity_type="commercial_offer",
        entity_id=offer_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    from app.workers.parse_cp import parse_cp_task
    celery_task = parse_cp_task.delay(str(offer_id), str(task.id))
    task.celery_task_id = celery_task.id
    await db.commit()

    return {
        "success": True,
        "data": {
            "task_id": task.id,
            "status": "ACCEPTED",
            "check_url": f"/api/v1/tasks/{task.id}",
        },
    }
