import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Supplier
from app.services.supplier_search_service import (
    search_suppliers_in_db,
    search_suppliers_combined,
)

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


@router.get("")
async def list_suppliers(
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Supplier)
    if search:
        query = query.where(Supplier.name.ilike(f"%{search}%") | Supplier.email.ilike(f"%{search}%"))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    suppliers = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.type,
                "email": s.email,
                "phone": s.phone,
                "inn": s.inn,
                "tags": s.tags,
                "is_active": s.is_active,
                "created_at": s.created_at,
            }
            for s in suppliers
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }


@router.post("/search")
async def search_suppliers(
    payload: SupplierSearch,
    db: AsyncSession = Depends(get_db),
):
    if payload.search_external:
        results = await search_suppliers_combined(db, payload.query, payload.limit)
    else:
        suppliers = await search_suppliers_in_db(db, payload.query, payload.limit)
        results = [
            {
                "id": s.id,
                "name": s.name,
                "email": s.email,
                "phone": s.phone,
                "website": s.website,
                "source": "internal_db",
                "match_relevance": "high" if payload.query.lower() in s.name.lower() else "medium",
                "is_new": False,
                "type": s.type,
                "snippet": "",
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
    return {"success": True, "data": {"id": supplier.id, "name": supplier.name}}


@router.get("/{supplier_id}")
async def get_supplier(supplier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Supplier not found"})
    return {
        "success": True,
        "data": {
            "id": supplier.id,
            "name": supplier.name,
            "type": supplier.type,
            "website": supplier.website,
            "email": supplier.email,
            "phone": supplier.phone,
            "inn": supplier.inn,
            "tags": supplier.tags,
            "is_active": supplier.is_active,
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
