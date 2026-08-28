from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.models import Tender, CommercialOffer, TenderPosition, Supplier


def evaluate_risks(
    tender: Tender,
    offer: Optional[CommercialOffer],
    settings: dict,
    tender_positions: Optional[List[TenderPosition]] = None,
    supplier: Optional[Supplier] = None,
) -> Dict:
    """Оценка рисков по ТЗ 8.10.
    Возвращает словарь с полями level (LOW/MEDIUM/HIGH) и factors.
    """
    factors = []
    risk_level = "LOW"

    # Ценовой риск
    if offer and offer.margin_percent is not None:
        min_margin = settings.get("min_margin_percent", 15.0)
        if offer.margin_percent < min_margin:
            price_risk = "HIGH"
        elif offer.margin_percent < min_margin * 1.5:
            price_risk = "MEDIUM"
        else:
            price_risk = "LOW"
        factors.append({"type": "price", "level": price_risk, "description": f"Маржа {offer.margin_percent:.1f}%"})
        if price_risk == "HIGH":
            risk_level = "HIGH"
        elif price_risk == "MEDIUM" and risk_level == "LOW":
            risk_level = "MEDIUM"

    # Риск сроков
    if tender.deadline_at:
        days_left = (tender.deadline_at - datetime.now(timezone.utc)).days
        if offer and offer.delivery_terms and offer.delivery_terms.get("delivery_days"):
            delivery_days = int(offer.delivery_terms["delivery_days"])
        else:
            delivery_days = 30
        buffer = days_left - delivery_days
        if buffer < 7:
            deadline_risk = "HIGH"
        elif buffer < 14:
            deadline_risk = "MEDIUM"
        else:
            deadline_risk = "LOW"
        factors.append({"type": "deadline", "level": deadline_risk, "description": f"Запас {buffer} дней"})
        if deadline_risk == "HIGH":
            risk_level = "HIGH"
        elif deadline_risk == "MEDIUM" and risk_level == "LOW":
            risk_level = "MEDIUM"

    # Риск соответствия
    if offer and offer.positions:
        analog_count = sum(1 for p in offer.positions if p.match_type == "analog")
        essential_ids = set()
        if tender_positions:
            essential_ids = {tp.id for tp in tender_positions if tp.is_essential}
        essential_analog = sum(1 for p in offer.positions if p.match_type == "analog" and p.tender_position_id in essential_ids)
        if essential_analog > 0:
            compliance_risk = "HIGH"
        elif analog_count > 0:
            compliance_risk = "MEDIUM"
        else:
            compliance_risk = "LOW"
        factors.append({"type": "compliance", "level": compliance_risk, "description": f"Аналогов: {analog_count}, критичных: {essential_analog}"})
        if compliance_risk == "HIGH":
            risk_level = "HIGH"
        elif compliance_risk == "MEDIUM" and risk_level == "LOW":
            risk_level = "MEDIUM"

    # Риск контрагента
    if supplier:
        if supplier.successful_deals == 0 and supplier.total_lots == 0:
            supplier_risk = "HIGH"
        elif supplier.successful_deals == 0:
            supplier_risk = "MEDIUM"
        else:
            supplier_risk = "LOW"
        if not supplier.inn:
            if supplier_risk == "LOW":
                supplier_risk = "MEDIUM"
            elif supplier_risk == "MEDIUM":
                supplier_risk = "HIGH"
        factors.append({"type": "supplier", "level": supplier_risk, "description": f"Поставщик: {supplier.name}"})
        if supplier_risk == "HIGH":
            risk_level = "HIGH"
        elif supplier_risk == "MEDIUM" and risk_level == "LOW":
            risk_level = "MEDIUM"

    if sum(1 for f in factors if f["level"] == "MEDIUM") >= 2:
        risk_level = "HIGH"

    return {"level": risk_level, "factors": factors}
