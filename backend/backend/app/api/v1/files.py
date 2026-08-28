import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models import File

router = APIRouter()

ALLOWED_ENTITY_TYPES = {"tender", "supplier", "communication"}


@router.post("/upload", status_code=201)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    entity_type: str = Query("tender"),
    entity_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if entity_type not in ALLOWED_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": f"entity_type must be one of {ALLOWED_ENTITY_TYPES}"})
    if not entity_id:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "entity_id is required"})
    if not file.filename:
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "Filename required"})

    ext = Path(file.filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    subdir = os.path.join(settings.upload_dir, entity_type)
    os.makedirs(subdir, exist_ok=True)
    path = os.path.join(subdir, stored_name)

    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)

    file_record = File(
        entity_type=entity_type,
        entity_id=entity_id,
        filename=file.filename,
        file_size_bytes=len(content),
        mime_type=file.content_type or "application/octet-stream",
        storage_path=path,
    )
    db.add(file_record)
    await db.commit()
    await db.refresh(file_record)

    return {
        "success": True,
        "data": {
            "id": file_record.id,
            "filename": file_record.filename,
            "file_size_bytes": file_record.file_size_bytes,
            "mime_type": file_record.mime_type,
            "storage_path": file_record.storage_path,
            "uploaded_at": file_record.uploaded_at,
            "download_url": f"/api/v1/files/{file_record.id}/download",
        },
    }


@router.get("/{file_id}/download")
async def download_file(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    file_record = await db.get(File, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "File not found"})
    if not os.path.exists(file_record.storage_path):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "File not found on disk"})
    return FileResponse(
        path=file_record.storage_path,
        filename=file_record.filename,
        media_type=file_record.mime_type,
    )


@router.delete("/{file_id}")
async def delete_file(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    file_record = await db.get(File, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "File not found"})
    if os.path.exists(file_record.storage_path):
        os.remove(file_record.storage_path)
    await db.delete(file_record)
    await db.commit()
    return {"success": True, "data": None}
