import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Category, Task
from app.services.embedding_service import get_embedding_or_empty

router = APIRouter()


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    keywords: list[str] = []
    parent_id: Optional[uuid.UUID] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[list[str]] = None
    parent_id: Optional[uuid.UUID] = None
    is_active: Optional[bool] = None


async def _generate_embedding(category: Category):
    text = f"{category.name} {category.description} {' '.join(category.keywords)}"
    category.embedding = await get_embedding_or_empty(text)


@router.get("")
async def list_categories(
    search: Optional[str] = None,
    parent_id: Optional[uuid.UUID] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    sort_by: str = "name",
    sort_order: str = "asc",
    db: AsyncSession = Depends(get_db),
):
    query = select(Category)
    if search:
        query = query.where(Category.name.ilike(f"%{search}%") | Category.keywords.cast(str).ilike(f"%{search}%"))
    if parent_id is not None:
        query = query.where(Category.parent_id == parent_id)
    if is_active is not None:
        query = query.where(Category.is_active == is_active)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    if sort_by == "name":
        query = query.order_by(Category.name.asc() if sort_order == "asc" else Category.name.desc())
    elif sort_by == "created_at":
        query = query.order_by(Category.created_at.asc() if sort_order == "asc" else Category.created_at.desc())

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    categories = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "keywords": c.keywords,
                "parent_id": c.parent_id,
                "is_active": c.is_active,
                "children_count": len(c.children),
                "tenders_matched_count": 0,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            }
            for c in categories
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }


@router.post("", status_code=201)
async def create_category(payload: CategoryCreate, db: AsyncSession = Depends(get_db)):
    if payload.parent_id:
        parent = await db.get(Category, payload.parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Parent category not found"})
    category = Category(
        name=payload.name,
        description=payload.description,
        keywords=payload.keywords,
        parent_id=payload.parent_id,
    )
    await _generate_embedding(category)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return {
        "success": True,
        "data": {
            "id": category.id,
            "name": category.name,
            "description": category.description,
            "keywords": category.keywords,
            "parent_id": category.parent_id,
            "is_active": category.is_active,
            "embedding_generated": True,
        },
    }


@router.get("/{category_id}")
async def get_category(category_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Category not found"})
    return {
        "success": True,
        "data": {
            "id": category.id,
            "name": category.name,
            "description": category.description,
            "keywords": category.keywords,
            "parent_id": category.parent_id,
            "parent_name": category.parent.name if category.parent else None,
            "children": [{"id": child.id, "name": child.name, "is_active": child.is_active} for child in category.children],
            "is_active": category.is_active,
            "embedding_status": "generated" if category.embedding else "missing",
            "embedding_dimensions": len(category.embedding) if category.embedding else 0,
            "embedding_generated_at": category.updated_at if category.embedding else None,
            "tenders_matched_count": 0,
            "created_at": category.created_at,
            "updated_at": category.updated_at,
        },
    }


@router.put("/{category_id}")
async def update_category_full(
    category_id: uuid.UUID, payload: CategoryUpdate, db: AsyncSession = Depends(get_db)
):
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Category not found"})
    if payload.name is None or payload.description is None:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "name and description are required"})
    category.name = payload.name
    category.description = payload.description
    category.keywords = payload.keywords or []
    category.parent_id = payload.parent_id
    await _generate_embedding(category)
    await db.commit()
    await db.refresh(category)
    return await get_category(category_id, db)


@router.patch("/{category_id}")
async def update_category(category_id: uuid.UUID, payload: CategoryUpdate, db: AsyncSession = Depends(get_db)):
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Category not found"})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    if "keywords" in payload.model_dump(exclude_unset=True) or "name" in payload.model_dump(exclude_unset=True) or "description" in payload.model_dump(exclude_unset=True):
        await _generate_embedding(category)
    await db.commit()
    await db.refresh(category)
    return await get_category(category_id, db)


@router.delete("/{category_id}")
async def delete_category(category_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Category not found"})
    category.is_active = False
    await db.commit()
    return {"success": True, "data": None}


@router.post("/{category_id}/re-embed")
async def reembed_category(category_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    category = await db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Category not found"})
    await _generate_embedding(category)
    await db.commit()
    return {"success": True, "data": {"message": "Embedding regenerated"}}


@router.post("/bulk-import", status_code=202)
async def bulk_import_categories(payload: list[CategoryCreate], db: AsyncSession = Depends(get_db)):
    from app.workers.import_categories import import_categories_task
    task = Task(
        task_type="IMPORT_CATEGORIES",
        status="PENDING",
        input_data={"categories": [item.model_dump() for item in payload]},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    celery_task = import_categories_task.delay([item.model_dump() for item in payload], str(task.id))
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
