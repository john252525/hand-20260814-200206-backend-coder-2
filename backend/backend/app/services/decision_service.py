from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tender, CommercialOffer, Decision, Supplier, TenderPosition
from app.services.risk_service import evaluate_risks
from app.services.settings_service import get_section


def get_auto_recommendation(margin_percent: Optional[float], risk_level: str, settings: dict) -> str:
    min_margin = settings.get("min_margin_percent", 15.0)
    max_risk = settings.get("max_risk_level", "MEDIUM")
    if margin_percent is None:
        return "REVIEW"
    if margin_percent < min_margin:
        return "REJECT"
    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    if risk_order.get(risk_level, 2) > risk_order.get(max_risk, 1):
        return "REVIEW"
    return "APPROVE"


async def create_decision(
    db: AsyncSession,
    tender: Tender,
    decision: str,
    reason: str,
    chosen_supplier_id=None,
    chosen_offer_id=None,
    tender_positions: Optional[List[TenderPosition]] = None,
) -> Decision:
    """Создаёт или обновляет решение по тендеру."""
    result = await db.execute(select(Decision).where(Decision.tender_id == tender.id))
    existing = result.scalar_one_or_none()

    settings = await get_section(db, "scoring")
    offer = None
    supplier = None
    if chosen_offer_id:
        offer = await db.get(CommercialOffer, chosen_offer_id)
    if chosen_supplier_id:
        supplier = await db.get(Supplier, chosen_supplier_id)

    if existing:
        existing.decision = decision
        existing.reason = reason
        existing.chosen_supplier_id = chosen_supplier_id
        existing.chosen_offer_id = chosen_offer_id
        existing.decided_at = datetime.now(timezone.utc)
        if offer:
            existing.margin_at_decision = offer.margin_absolute
        risk = evaluate_risks(
            tender, offer, settings,
            tender_positions=tender_positions or [],
            supplier=supplier,
        )
        existing.risk_level_at_decision = risk["level"]
        return existing

    risk = evaluate_risks(
        tender, offer, settings,
        tender_positions=tender_positions or [],
        supplier=supplier,
    )
    dec = Decision(
        tender_id=tender.id,
        decision=decision,
        chosen_supplier_id=chosen_supplier_id,
        chosen_offer_id=chosen_offer_id,
        margin_at_decision=offer.margin_absolute if offer else None,
        risk_level_at_decision=risk["level"],
        reason=reason,
    )
    db.add(dec)
    return dec
