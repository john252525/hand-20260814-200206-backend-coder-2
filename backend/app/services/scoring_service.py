from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional, Tuple

from app.models import Tender


def calculate_score(
    tender: Tender,
    settings: dict,
    requirements=None,
) -> Tuple[float, Dict]:
    """Возвращает (total_score, score_components)."""
    w_margin = settings.get("weight_margin", 40)
    w_simplicity = settings.get("weight_simplicity", 30)
    w_volume = settings.get("weight_volume", 20)
    w_competition = settings.get("weight_competition", 10)

    margin_score = _margin_score(tender, settings)
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


def _margin_score(tender: Tender, settings: dict) -> float:
    if not tender.nmck or tender.nmck <= 0:
        return settings.get("margin_fallback_score", 50)
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
