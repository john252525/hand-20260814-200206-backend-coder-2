import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models import Task

router = APIRouter()

@router.get("")
async def list_tasks(
    status: Optional[str] = None,
    task_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[uuid.UUID] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Task)
    if status:
        query = query.where(Task.status == status)
    if task_type:
        query = query.where(Task.task_type == task_type)
    if entity_type:
        query = query.where(Task.entity_type == entity_type)
    if entity_id:
        query = query.where(Task.entity_id == entity_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.order_by(Task.created_at.desc()).offset((page - 1) * per_page).limit(per_page))
    tasks = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": t.id,
                "celery_task_id": t.celery_task_id,
                "task_type": t.task_type,
                "status": t.status,
                "progress_percent": t.progress_percent,
                "entity_type": t.entity_type,
                "entity_id": t.entity_id,
                "result_summary": t.result_summary,
                "error_message": t.error_message,
                "created_at": t.created_at,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
            }
            for t in tasks
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }

@router.get("/{task_id}")
async def get_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Task not found"})
    return {
        "success": True,
        "data": {
            "id": task.id,
            "celery_task_id": task.celery_task_id,
            "task_type": task.task_type,
            "status": task.status,
            "progress_percent": task.progress_percent,
            "entity_type": task.entity_type,
            "entity_id": task.entity_id,
            "result_summary": task.result_summary,
            "error_message": task.error_message,
            "input_data": task.input_data,
            "output_data": task.output_data,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
        },
    }

@router.post("/{task_id}/cancel")
async def cancel_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Task not found"})
    if task.status not in ("PENDING", "IN_PROGRESS"):
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "Task cannot be cancelled"})
    task.status = "CANCELLED"
    task.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"success": True, "data": {"id": task.id, "status": "CANCELLED"}}
