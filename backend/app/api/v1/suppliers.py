import uuid
from typing import Optional
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models import Supplier, LotSupplier, Communication
from app.services.supplier_search_service import search_suppliers_in_db, search_suppliers_combined
from app.services.webhook_integration import notify_supplier_created
logger = structlog.get_logger(__name__)
router = APIRouter()

class SupplierCreate(BaseModel):
    name: str
    type: str = "unknown"
    website: str = ""
    email: Optional[str] = ""
    phone: str = ""
    telegram: str = ""
    whatsapp: str = ""
    inn: str = ""
    kpp: str = ""
    ogrn: str = ""
    legal_address: str = ""
    tags: list[str] = []
    notes: str = ""
    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        import re
        if v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v

class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    whatsapp: Optional[str] = None
    inn: Optional[str] = None
    kpp: Optional[str] = None
    ogrn: Optional[str] = None
    legal_address: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        import re
        if v and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v

class SupplierSearch(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(10, ge=1, le=100)
    search_external: bool = True

class MergePayload(BaseModel):
    primary_id: uuid.UUID
    secondary_id: uuid.UUID

@router.get("")
async def list_suppliers(
    search: Optional[str] = None,
    type: Optional[str] = None,
    tags: Optional[str] = None,
    has_email: Optional[bool] = None,
    has_phone: Optional[bool] = None,
    is_active: Optional[bool] = None,
    min_successful_deals: Optional[int] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: AsyncSession = Depends(get_db),
):
    query = select(Supplier)
    if search:
        query = query.where(Supplier.name.ilike(f"%{search}%") | Supplier.email.ilike(f"%{search}%"))
    if type:
        query = query.where(Supplier.type == type)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            query = query.where(Supplier.tags.cast(str).ilike(f"%{tag}%"))
    if has_email is not None:
        if has_email:
            query = query.where(Supplier.email != "")
        else:
            query = query.where(Supplier.email == "")
    if has_phone is not None:
        if has_phone:
            query = query.where(Supplier.phone != "")
        else:
            query = query.where(Supplier.phone == "")
    if is_active is not None:
        query = query.where(Supplier.is_active == is_active)
    if min_successful_deals is not None:
        query = query.where(Supplier.successful_deals >= min_successful_deals)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    valid_sort = {"name", "created_at", "successful_deals", "total_volume_rub"}
    if sort_by not in valid_sort:
        sort_by = "created_at"
    sort_col = getattr(Supplier, sort_by, Supplier.created_at)
    if sort_order == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    suppliers = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": s.id, "name": s.name, "type": s.type, "website": s.website, "email": s.email,
                "phone": s.phone, "telegram": s.telegram, "inn": s.inn, "tags": s.tags,
                "rating": s.rating, "total_lots": s.total_lots, "successful_deals": s.successful_deals,
                "total_volume_rub": s.total_volume_rub, "is_active": s.is_active, "created_at": s.created_at,
            }
            for s in suppliers
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }

@router.post("/search")
async def search_suppliers(payload: SupplierSearch, db: AsyncSession = Depends(get_db)):
    if payload.search_external:
        results = await search_suppliers_combined(db, payload.query, payload.limit)
    else:
        suppliers = await search_suppliers_in_db(db, payload.query, payload.limit)
        results = [
            {
                "id": s.id, "name": s.name, "email": s.email, "phone": s.phone, "website": s.website,
                "source": "internal_db", "match_relevance": "high" if payload.query.lower() in s.name.lower() else "medium",
                "is_new": False, "type": s.type, "snippet": "",
            }
            for s in suppliers
        ]
    return {"success": True, "data": results}

@router.post("", status_code=201)
async def create_supplier(payload: SupplierCreate, db: AsyncSession = Depends(get_db)):
    if payload.email:
        existing = await db.execute(select(Supplier).where(Supplier.email == payload.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "Supplier with this email already exists"})
    if payload.inn:
        existing = await db.execute(select(Supplier).where(Supplier.inn == payload.inn))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "Supplier with this INN already exists"})
    supplier = Supplier(**payload.model_dump())
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    logger.info("supplier.created", supplier_id=str(supplier.id), name=supplier.name)
    await notify_supplier_created(supplier.id)  # <-- подключено уведомление
    return {"success": True, "data": {"id": supplier.id, "name": supplier.name}}

@router.post("/merge")
async def merge_suppliers(payload: MergePayload, db: AsyncSession = Depends(get_db)):
    primary = await db.get(Supplier, payload.primary_id)
    secondary = await db.get(Supplier, payload.secondary_id)
    if not primary or not secondary:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Supplier not found"})
    for field in ["name", "type", "website", "email", "phone", "telegram", "whatsapp", "inn", "kpp", "ogrn", "legal_address", "notes"]:
        if not getattr(primary, field) and getattr(secondary, field):
            setattr(primary, field, getattr(secondary, field))
    combined_tags = list(set(primary.tags + secondary.tags))
    primary.tags = combined_tags
    result = await db.execute(select(LotSupplier).where(LotSupplier.supplier_id == secondary.id))
    for ls in result.scalars().all():
        existing = await db.execute(select(LotSupplier).where(LotSupplier.tender_id == ls.tender_id, LotSupplier.supplier_id == primary.id))
        if existing.scalar_one_or_none():
            await db.delete(ls)
        else:
            ls.supplier_id = primary.id
    primary.total_lots += secondary.total_lots
    primary.successful_deals += secondary.successful_deals
    primary.total_volume_rub = (primary.total_volume_rub or 0) + (secondary.total_volume_rub or 0)
    secondary.is_active = False
    secondary.deleted_at = func.now()
    await db.commit()
    return {"success": True, "data": {"primary_id": primary.id, "merged_from": secondary.id}}

@router.get("/{supplier_id}")
async def get_supplier(supplier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Supplier not found"})
    lots = (await db.execute(
        select(LotSupplier)
        .where(LotSupplier.supplier_id == supplier_id)
        .options(
            selectinload(LotSupplier.tender),
            selectinload(LotSupplier.commercial_offers),
        )
    )).scalars().all()
    recent = []
    for ls in lots:
        recent.append({
            "tender_id": ls.tender_id,
            "tender_title": ls.tender.title if ls.tender else None,
            "status": ls.tender.status if ls.tender else None,
            "margin_percent": None,
            "date": ls.tender.created_at if ls.tender else None,
        })
    return {
        "success": True,
        "data": {
            "id": supplier.id,
            "name": supplier.name,
            "type": supplier.type,
            "website": supplier.website,
            "contacts": {
                "email": supplier.email, "phone": supplier.phone, "telegram": supplier.telegram,
                "whatsapp": supplier.whatsapp, "contact_persons": supplier.contact_persons,
            },
            "legal_info": {"inn": supplier.inn, "kpp": supplier.kpp, "ogrn": supplier.ogrn, "legal_address": supplier.legal_address},
            "tags": supplier.tags,
            "notes": supplier.notes,
            "rating": supplier.rating,
            "statistics": {
                "total_lots": supplier.total_lots,
                "cp_received": len([ls for ls in lots if ls.commercial_offers]),
                "successful_deals": supplier.successful_deals,
                "total_volume_rub": supplier.total_volume_rub,
            },
            "recent_tenders": recent,
            "is_active": supplier.is_active,
            "deleted_at": supplier.deleted_at,
            "created_at": supplier.created_at,
            "updated_at": supplier.updated_at,
        },
    }

@router.patch("/{supplier_id}")
async def update_supplier(supplier_id: uuid.UUID, payload: SupplierUpdate, db: AsyncSession = Depends(get_db)):
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Supplier not found"})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, field, value)
    await db.commit()
    await db.refresh(supplier)
    return {"success": True, "data": {"id": supplier.id, "name": supplier.name}}

@router.delete("/{supplier_id}")
async def delete_supplier(supplier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Supplier not found"})
    supplier.is_active = False
    await db.commit()
    return {"success": True, "data": None}

@router.get("/{supplier_id}/communications")
async def supplier_communications(supplier_id: uuid.UUID, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Supplier not found"})
    query = (
        select(Communication)
        .join(LotSupplier, Communication.lot_supplier_id == LotSupplier.id)
        .where(LotSupplier.supplier_id == supplier_id)
        .options(selectinload(Communication.lot_supplier).selectinload(LotSupplier.tender))
        .order_by(Communication.created_at.desc())
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    comms = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": c.id, "tender_id": c.tender_id,
                "tender_title": c.lot_supplier.tender.title if c.lot_supplier and c.lot_supplier.tender else None,
                "direction": c.direction, "channel": c.channel, "subject": c.subject,
                "body_preview": c.body_text[:200], "has_attachments": False, "message_type": c.message_type,
                "sent_at": c.sent_at, "received_at": c.received_at,
            }
            for c in comms
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }
