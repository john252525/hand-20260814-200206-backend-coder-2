from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Tender, CommercialOffer, OfferPosition, TenderPosition

async def estimate_margin_percent(db: AsyncSession, tender: Tender) -> Optional[float]:
    """Оценка маржи на основе средней цены из предыдущих КП по аналогичным позициям.
    Возвращает процент маржи или None, если данных недостаточно.
    """
    if not tender.nmck or tender.nmck <= 0:
        return None
    # Собираем названия позиций тендера
    tender_positions = await db.execute(
        select(TenderPosition).where(TenderPosition.tender_id == tender.id)
    )
    positions = tender_positions.scalars().all()
    if not positions:
        return None

    # Для каждой позиции ищем среднюю цену из offer_positions с похожим названием
    total_estimated_cost = Decimal("0")
    total_quantity = Decimal("0")
    for pos in positions:
        # Ищем похожие позиции в других КП (по совпадению ключевых слов или названия)
        search_term = f"%{pos.name[:50]}%"
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

async def calculate_score(
    tender: Tender,
    settings: dict,
    requirements=None,
    db: Optional[AsyncSession] = None,
) -> Tuple[float, Dict]:
    """Возвращает (total_score, score_components)."""
    w_margin = settings.get("weight_margin", 40)
    w_simplicity = settings.get("weight_simplicity", 30)
    w_volume = settings.get("weight_volume", 20)
    w_competition = settings.get("weight_competition", 10)

    margin_score = await _margin_score(tender, settings, db)
    simplicity_score = _simplicity_score(requirements, settings)
    volume_score = _volume_score(tender.nmck, settings)
    competition_score = settings.get("default_competition_score", 50)

    total = (
        w_margin * margin_score
        + w_simplicity * simplicity_score
        + w_volume * volume_score
        + w_competition * competition_score
    ) / 100
    components = {
        "margin_score": margin_score,
        "simplicity_score": simplicity_score,
        "volume_score": volume_score,
        "competition_score": competition_score,
    }
    return round(total, 2), components

async def _margin_score(tender: Tender, settings: dict, db: Optional[AsyncSession] = None) -> float:
    if not tender.nmck or tender.nmck <= 0:
        return settings.get("margin_fallback_score", 50)

    mode = settings.get("margin_calculation_mode", "auto")
    if mode == "auto" and db:
        est_margin = await estimate_margin_percent(db, tender)
        if est_margin is not None:
            # Линейно до 30% маржи = 100 баллов
            score = max(0, min(100, est_margin / 0.30 * 100))
            return score
    return settings.get("margin_fallback_score", 50)

def _simplicity_score(requirements, settings: dict) -> float:
    score = 100.0
    if requirements:
        if requirements.license_required:
            score -= 50
        if requirements.sro_required:
            score -= 50
        if requirements.special_conditions:
            score -= min(20, len(requirements.special_conditions) * 5)
        if requirements.stages_count and requirements.stages_count > 1:
            score -= min(20, (requirements.stages_count - 1) * 10)
    return max(0, score)

def _volume_score(nmck: Decimal | None, settings: dict) -> float:
    if not nmck:
        return settings.get("volume_scores", {}).get("low", 20)
    thresholds = settings.get("volume_thresholds", {})
    scores = settings.get("volume_scores", {})
    if nmck < thresholds.get("low", 100000):
        return scores.get("low", 20)
    if nmck < thresholds.get("medium", 1000000):
        return scores.get("medium", 50)
    if nmck < thresholds.get("high", 5000000):
        return scores.get("high", 80)
    return scores.get("very_high", 95)