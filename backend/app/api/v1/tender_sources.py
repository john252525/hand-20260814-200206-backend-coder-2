import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models import TenderSource, Task

router = APIRouter()


class SourceCreate(BaseModel):
    name: str
    type: str
    api_url: str
    api_key: Optional[str] = None
    config: dict = {}


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    api_url: Optional[str] = None
    is_active: Optional[bool] = None
    config: Optional[dict] = None


class SyncRequest(BaseModel):
    since: Optional[str] = None
    full_resync: bool = False


@router.get("")
async def list_sources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TenderSource))
    sources = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.type,
                "api_url": s.api_url,
                "is_active": s.is_active,
                "last_sync_at": s.last_sync_at,
                "last_sync_status": s.last_sync_status,
                "last_error": s.last_error,
            }
            for s in sources
        ],
    }


@router.post("", status_code=201)
async def create_source(payload: SourceCreate, db: AsyncSession = Depends(get_db)):
    source = TenderSource(
        name=payload.name,
        type=payload.type,
        api_url=payload.api_url,
        api_key_encrypted=payload.api_key or "",
        config=payload.config,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return {"success": True, "data": {"id": source.id, "name": source.name}}


@router.get("/{source_id}")
async def get_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    source = await db.get(TenderSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Source not found"})
    return {
        "success": True,
        "data": {
            "id": source.id,
            "name": source.name,
            "type": source.type,
            "api_url": source.api_url,
            "config": source.config,
            "is_active": source.is_active,
            "last_sync_at": source.last_sync_at,
            "last_sync_status": source.last_sync_status,
            "last_error": source.last_error,
            "created_at": source.created_at,
        },
    }


@router.patch("/{source_id}")
async def update_source(source_id: uuid.UUID, payload: SourceUpdate, db: AsyncSession = Depends(get_db)):
    source = await db.get(TenderSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Source not found"})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, field, value)
    await db.commit()
    await db.refresh(source)
    return {"success": True, "data": {"id": source.id}}


@router.delete("/{source_id}")
async def delete_source(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    source = await db.get(TenderSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Source not found"})
    source.is_active = False
    await db.commit()
    return {"success": True, "data": None}


@router.post("/{source_id}/sync", status_code=202)
async def sync_source(
    source_id: uuid.UUID,
    payload: Optional[SyncRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    from app.workers.sync_tenders import sync_tenders
    existing = await db.get(TenderSource, source_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Source not found"})
    # Защита от параллельных задач
    existing_task = await db.execute(
        select(Task).where(
            Task.entity_type == "tender_source",
            Task.entity_id == source_id,
            Task.task_type == "SYNC_TENDERS",
            Task.status.in_(["PENDING", "IN_PROGRESS"]),
        )
    )
    if existing_task.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "Sync already in progress"})
    task = Task(
        task_type="SYNC_TENDERS",
        status="PENDING",
        entity_type="tender_source",
        entity_id=source_id,
        input_data={"since": payload.since if payload else None, "full_resync": payload.full_resync if payload else False},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    celery_task = sync_tenders.delay(str(source_id), str(task.id))
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


@router.post("/{source_id}/test-connection")
async def test_connection(source_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    import httpx
    source = await db.get(TenderSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Source not found"})
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            start = __import__('time').time()
            resp = await client.get(source.api_url, params={"limit": 1})
            latency_ms = int((__import__('time').time() - start) * 1000)
            return {
                "success": True,
                "data": {
                    "reachable": resp.status_code < 500,
                    "latency_ms": latency_ms,
                    "tenders_available": None,
                    "error": None if resp.status_code < 500 else f"HTTP {resp.status_code}",
                },
            }
    except Exception as e:
        return {
            "success": True,
            "data": {
                "reachable": False,
                "latency_ms": None,
                "tenders_available": None,
                "error": str(e),
            },
        }
