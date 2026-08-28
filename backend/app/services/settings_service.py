from typing import Any, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting


async def get_settings_dict(db: AsyncSession) -> Dict[str, Dict[str, Any]]:
    """Возвращает все настройки в виде словаря {section: {key: value}}."""
    result = await db.execute(select(Setting))
    settings = result.scalars().all()
    grouped: Dict[str, Dict[str, Any]] = {}
    for s in settings:
        grouped.setdefault(s.section, {})[s.key] = s.value
    return grouped


async def get_section(db: AsyncSession, section: str) -> Dict[str, Any]:
    result = await db.execute(select(Setting).where(Setting.section == section))
    return {s.key: s.value for s in result.scalars().all()}
