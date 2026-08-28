import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Task

router = APIRouter()


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
