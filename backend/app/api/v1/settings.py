from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models import Setting, SettingHistory

router = APIRouter()


@router.get("")
async def get_all_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting))
    settings = result.scalars().all()
    grouped: Dict[str, Dict[str, Any]] = {}
    for s in settings:
        grouped.setdefault(s.section, {})[s.key] = s.value
    return {"success": True, "data": grouped}


@router.get("/{section}")
async def get_section(section: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Setting).where(Setting.section == section))
    settings = result.scalars().all()
    if not settings:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Section '{section}' not found"})
    return {"success": True, "data": {s.key: s.value for s in settings}}


async def _save_section(section: str, payload: Dict[str, Any], db: AsyncSession, replace: bool = False):
    result = await db.execute(select(Setting).where(Setting.section == section))
    existing = {s.key: s for s in result.scalars().all()}
    if replace:
        # Удаляем ключи, которых нет в payload
        for key in existing.keys() - payload.keys():
            setting = existing[key]
            db.add(SettingHistory(setting_id=setting.id, section=section, key=key, old_value=setting.value, new_value=None))
            await db.delete(setting)
    for key, value in payload.items():
        if key in existing:
            setting = existing[key]
            if setting.value != value:
                old_value = setting.value
                setting.value = value
                db.add(SettingHistory(setting_id=setting.id, section=section, key=key, old_value=old_value, new_value=value))
        else:
            setting = Setting(section=section, key=key, value=value, description="")
            db.add(setting)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "Duplicate setting key"})


@router.put("/{section}")
async def update_section(section: str, payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    await _save_section(section, payload, db, replace=True)
    return await get_section(section, db)


@router.patch("/{section}")
async def patch_section(section: str, payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    await _save_section(section, payload, db, replace=False)
    return await get_section(section, db)


@router.get("/history")
async def get_history(
    section: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(SettingHistory).order_by(SettingHistory.changed_at.desc())
    if section:
        query = query.where(SettingHistory.section == section)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    history = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": h.id,
                "section": h.section,
                "key": h.key,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "changed_at": h.changed_at,
            }
            for h in history
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }
