import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Tender, TenderStatusHistory, LotSupplier, Supplier, Task
from app.services.tender_status_service import change_tender_status

router = APIRouter()


class TenderCreate(BaseModel):
    source_id: uuid.UUID
    source_tender_id: str
    title: str
    description: str = ""
    nmck: Optional[Decimal] = None
    currency: str = "RUB"
    published_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    customer_name: str = ""
    customer_inn: str = ""
    customer_kpp: str = ""
    platform: str = ""
    source_url: str = ""


class TenderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    nmck: Optional[Decimal] = None
    status: Optional[str] = None
    customer_name: Optional[str] = None


class SupplierConfirm(BaseModel):
    supplier_ids: list[uuid.UUID] = []
    new_suppliers: list[dict] = []
    source_by_id: dict[str, str] = {}


class RequestCpPayload(BaseModel):
    supplier_ids: list[uuid.UUID] = []


@router.get("")
async def list_tenders(
    status: Optional[str] = None,
    category_id: Optional[uuid.UUID] = None,
    nmck_min: Optional[Decimal] = None,
    nmck_max: Optional[Decimal] = None,
    deadline_after: Optional[datetime] = None,
    deadline_before: Optional[datetime] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Tender)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        query = query.where(Tender.status.in_(statuses))
    if category_id:
        query = query.where(Tender.matched_category_id == category_id)
    if nmck_min is not None:
        query = query.where(Tender.nmck >= nmck_min)
    if nmck_max is not None:
        query = query.where(Tender.nmck <= nmck_max)
    if deadline_after:
        query = query.where(Tender.deadline_at >= deadline_after)
    if deadline_before:
        query = query.where(Tender.deadline_at <= deadline_before)
    if search:
        query = query.where(Tender.title.ilike(f"%{search}%") | Tender.customer_name.ilike(f"%{search}%"))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.order_by(Tender.created_at.desc()).offset((page - 1) * per_page).limit(per_page))
    tenders = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": t.id,
                "source_tender_id": t.source_tender_id,
                "title": t.title,
                "description": t.description[:300] if t.description else "",
                "nmck": t.nmck,
                "currency": t.currency,
                "published_at": t.published_at,
                "deadline_at": t.deadline_at,
                "customer_name": t.customer_name,
                "status": t.status,
                "score": t.score,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tenders
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }


@router.post("", status_code=201)
async def create_tender(payload: TenderCreate, db: AsyncSession = Depends(get_db)):
    tender = Tender(**payload.model_dump())
    db.add(tender)
    await db.flush()
    await change_tender_status(db, tender, "NEW", note="Тендер создан вручную")
    await db.commit()
    await db.refresh(tender)
    return {"success": True, "data": {"id": tender.id, "status": tender.status}}


@router.get("/stats")
async def tender_stats(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(Tender))
    by_status = {}
    result = await db.execute(select(Tender.status, func.count()).group_by(Tender.status))
    for status, count in result.all():
        by_status[status] = count
    return {
        "success": True,
        "data": {
            "total": total,
            "by_status": by_status,
            "by_category": [],
            "avg_processing_time_minutes": 0,
            "approval_rate_percent": 0,
            "avg_margin_percent": 0,
            "total_approved_volume_rub": 0,
        },
    }


@router.get("/{tender_id}")
async def get_tender(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})
    return {
        "success": True,
        "data": {
            "id": tender.id,
            "source_id": tender.source_id,
            "source_tender_id": tender.source_tender_id,
            "title": tender.title,
            "description": tender.description,
            "nmck": tender.nmck,
            "status": tender.status,
            "customer_name": tender.customer_name,
            "score": tender.score,
            "created_at": tender.created_at,
            "updated_at": tender.updated_at,
        },
    }


@router.get("/{tender_id}/timeline")
async def get_timeline(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TenderStatusHistory)
        .where(TenderStatusHistory.tender_id == tender_id)
        .order_by(TenderStatusHistory.set_at.asc())
    )
    history = result.scalars().all()
    if not history:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})
    return {
        "success": True,
        "data": [
            {
                "timestamp": h.set_at,
                "event_type": "STATUS_CHANGE",
                "description": f"{h.previous_status or ''} -> {h.status}" + (f" ({h.note})" if h.note else ""),
                "details": {},
            }
            for h in history
        ],
    }


@router.patch("/{tender_id}")
async def update_tender(tender_id: uuid.UUID, payload: TenderUpdate, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tender, field, value)
    if payload.status:
        await change_tender_status(db, tender, payload.status, note="Статус обновлён вручную")
    await db.commit()
    await db.refresh(tender)
    return {"success": True, "data": {"id": tender.id, "status": tender.status}}


@router.post("/{tender_id}/reprocess", status_code=202)
async def reprocess_tender(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from app.workers.process_tender import process_tender

    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})

    # Защита от параллельных задач
    existing_task = await db.execute(
        select(Task).where(
            Task.entity_type == "tender",
            Task.entity_id == tender_id,
            Task.task_type == "PROCESS_TENDER",
            Task.status.in_(["PENDING", "IN_PROGRESS"]),
        )
    )
    if existing_task.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "Processing already in progress"})

    task = Task(
        task_type="PROCESS_TENDER",
        status="PENDING",
        entity_type="tender",
        entity_id=tender_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    celery_task = process_tender.delay(str(tender_id), str(task.id))
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


@router.post("/{tender_id}/supplier-search-results/confirm")
async def confirm_suppliers(
    tender_id: uuid.UUID,
    payload: SupplierConfirm,
    db: AsyncSession = Depends(get_db),
):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})

    linked = 0
    for supplier_id in payload.supplier_ids:
        supplier = await db.get(Supplier, supplier_id)
        if not supplier:
            continue
        existing = await db.execute(
            select(LotSupplier).where(
                LotSupplier.tender_id == tender_id,
                LotSupplier.supplier_id == supplier_id,
            )
        )
        if existing.scalar_one_or_none():
            continue
        source = payload.source_by_id.get(str(supplier_id), "internal_db")
        db.add(LotSupplier(tender_id=tender_id, supplier_id=supplier_id, source=source))
        linked += 1

    for item in payload.new_suppliers:
        name = item.get("name")
        email = item.get("email", "")
        if not name:
            continue
        existing_supplier = None
        if email:
            existing_supplier = (await db.execute(select(Supplier).where(Supplier.email == email))).scalar_one_or_none()
        if not existing_supplier and item.get("inn"):
            existing_supplier = (await db.execute(select(Supplier).where(Supplier.inn == item["inn"]))).scalar_one_or_none()

        if existing_supplier:
            existing_ls = (await db.execute(
                select(LotSupplier).where(
                    LotSupplier.tender_id == tender_id,
                    LotSupplier.supplier_id == existing_supplier.id,
                )
            )).scalar_one_or_none()
            if not existing_ls:
                db.add(LotSupplier(tender_id=tender_id, supplier_id=existing_supplier.id, source="internal_db"))
                linked += 1
            continue

        supplier = Supplier(
            name=name,
            email=email,
            phone=item.get("phone", ""),
            website=item.get("website", ""),
            type=item.get("type", "unknown"),
            tags=item.get("tags", []),
        )
        db.add(supplier)
        await db.flush()
        db.add(LotSupplier(tender_id=tender_id, supplier_id=supplier.id, source=item.get("source", "google")))
        linked += 1

    await change_tender_status(db, tender, "SUPPLIERS_FOUND", note=f"Привязано поставщиков: {linked}")
    await db.commit()
    return {"success": True, "data": {"linked": linked}}


@router.post("/{tender_id}/request-cp", status_code=202)
async def request_cp(
    tender_id: uuid.UUID,
    payload: RequestCpPayload,
    db: AsyncSession = Depends(get_db),
):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Tender not found"})

    from app.workers.send_communications import send_cp_requests

    task = Task(
        task_type="SEND_CP",
        status="PENDING",
        entity_type="tender",
        entity_id=tender_id,
        input_data={"supplier_ids": [str(s) for s in payload.supplier_ids]},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    celery_task = send_cp_requests.delay(
        str(tender_id),
        str(task.id),
        [str(s) for s in payload.supplier_ids],
    )
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
