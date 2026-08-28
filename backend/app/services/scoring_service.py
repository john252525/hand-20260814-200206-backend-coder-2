from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tender, OfferPosition, TenderPosition, LotSupplier

async def estimate_margin_percent(db: AsyncSession, tender: Tender) -> Optional[float]:
    if not tender.nmck or tender.nmck <= 0:
        return None
    tender_positions = (await db.execute(
        select(TenderPosition).where(TenderPosition.tender_id == tender.id)
    )).scalars().all()
    if not tender_positions:
        return None
    total_estimated_cost = Decimal('0')
    total_quantity = Decimal('0')
    for pos in tender_positions:
        search_term = f'%{pos.name[:50]}%'
        avg_price = await db.scalar(
            select(func.avg(OfferPosition.price_per_unit)).where(
                OfferPosition.supplier_name.ilike(search_term),
                OfferPosition.price_per_unit.isnot(None),
            )
        )
        if avg_price is None:
            continue
        total_estimated_cost += Decimal(str(avg_price)) * pos.quantity
        total_quantity += pos.quantity
    if total_quantity == 0 or total_estimated_cost == 0:
        return None
    margin = (tender.nmck - total_estimated_cost) / tender.nmck * 100
    return float(margin)

def _simplicity_score(requirements, settings: dict, company_settings: Optional[dict], positions_count: int = 0) -> float:
    score = 100.0
    if requirements:
        if requirements.license_required and not (company_settings or {}).get('has_license', False):
            score -= 50
        if requirements.sro_required and not (company_settings or {}).get('has_sro', False):
            score -= 50
        if requirements.special_conditions:
            score -= min(20, len(requirements.special_conditions) * 5)
        if requirements.stages_count and requirements.stages_count > 1:
            score -= min(20, (requirements.stages_count - 1) * 10)
        if requirements.delivery_date:
            days = (requirements.delivery_date - datetime.now(timezone.utc)).days
            if days < 7:
                score -= 30
            elif days < 14:
                score -= 15
    if positions_count > 10:
        extra = (positions_count - 10 + 4) // 5
        score -= min(20, extra * 5)
    return max(0, score)

def _volume_score(nmck: Decimal | None, settings: dict) -> float:
    if not nmck:
        return settings.get('volume_scores', {}).get('low', 20)
    thresholds = settings.get('volume_thresholds', {})
    scores = settings.get('volume_scores', {})
    if nmck < thresholds.get('low', 100000):
        return scores.get('low', 20)
    if nmck < thresholds.get('medium', 1000000):
        return scores.get('medium', 50)
    if nmck < thresholds.get('high', 5000000):
        return scores.get('high', 80)
    return scores.get('very_high', 95)

async def _competition_score(db: AsyncSession, tender: Tender, settings: dict) -> float:
    """Оценка конкурентности.
    TODO: Реализовать расчёт на основе исторических данных категории.
    Сейчас используется заглушка для стабильности.
    """
    return settings.get('default_competition_score', 50)

async def calculate_score(
    tender: Tender,
    settings: dict,
    requirements=None,
    db: Optional[AsyncSession] = None,
    company_settings: Optional[dict] = None,
) -> Tuple[float, Dict]:
    w_margin = settings.get('weight_margin', 40)
    w_simplicity = settings.get('weight_simplicity', 30)
    w_volume = settings.get('weight_volume', 20)
    w_competition = settings.get('weight_competition', 10)

    margin_score = settings.get('margin_fallback_score', 50)
    if settings.get('margin_calculation_mode', 'auto') == 'auto' and db:
        est_margin = await estimate_margin_percent(db, tender)
        if est_margin is not None:
            margin_score = max(0, min(100, est_margin / 0.30 * 100))

    positions_count = len(tender.positions) if tender.positions else 0
    simplicity_score = _simplicity_score(requirements, settings, company_settings, positions_count)
    volume_score = _volume_score(tender.nmck, settings)
    competition_score = await _competition_score(db, tender, settings) if db else settings.get('default_competition_score', 50)

    total = (
        w_margin * margin_score
        + w_simplicity * simplicity_score
        + w_volume * volume_score
        + w_competition * competition_score
    ) / 100

    components = {
        'margin_score': margin_score,
        'simplicity_score': simplicity_score,
        'volume_score': volume_score,
        'competition_score': competition_score,
    }
    return round(total, 2), components
