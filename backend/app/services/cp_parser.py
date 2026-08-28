import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Tuple, Optional
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models import CommercialOffer, Tender, TenderPosition, OfferPosition
from app.services.llm_service import chat_completion

logger = structlog.get_logger(__name__)

CP_EXTRACT_PROMPT = """
Ты — анализатор коммерческих предложений. Извлеки из предоставленного текста структурированные данные.
Текст КП:
{cp_text}
Позиции тендера (для сопоставления):
{tender_positions_json}
Извлеки строго в формате JSON:
{{
  "positions": [
    {{
      "tender_position_number": 1,
      "supplier_name": "название у поставщика",
      "match_type": "exact" | "analog" | "not_found",
      "price_per_unit": 12345.67,
      "quantity_available": 100,
      "delivery_days": 14,
      "nds_included": true,
      "nds_rate": 20,
      "notes": ""
    }}
  ],
  "delivery_terms": {{
    "delivery_address": "",
    "delivery_days": 14,
    "delivery_cost": 5000.00,
    "delivery_conditions": ""
  }},
  "payment_terms": {{
    "prepayment_percent": 30,
    "deferred_payment_days": 0,
    "description": ""
  }},
  "valid_until": "YYYY-MM-DD или null"
}}
Правила:
- match_type = "exact" если позиция полностью соответствует тендерной (тот же бренд/модель/характеристики)
- match_type = "analog" если предлагается замена с аналогичными характеристиками
- match_type = "not_found" если позиция отсутствует в КП
- Если цена не указана — price_per_unit = null
- Если НДС не указан явно — считать nds_included = true, nds_rate = 20 (для РФ)
- Все числа — без разделителей тысяч, десятичный разделитель — точка
Ответ — ТОЛЬКО JSON.
"""

async def parse_cp_text(
    db: AsyncSession,
    tender: Tender,
    cp_text: str,
) -> Tuple[dict, List[TenderPosition]]:
    result = await db.execute(
        select(TenderPosition).where(TenderPosition.tender_id == tender.id)
    )
    positions = list(result.scalars().all())
    if not settings.llm_api_key:
        return _fallback_parse(positions, cp_text), positions

    positions_json = json.dumps(
        [
            {
                "position_number": p.position_number,
                "name": p.name,
                "characteristics": p.characteristics,
                "quantity": float(p.quantity),
                "unit": p.unit,
            }
            for p in positions
        ],
        ensure_ascii=False,
    )
    prompt = CP_EXTRACT_PROMPT.format(
        cp_text=cp_text[:12000],
        tender_positions_json=positions_json,
    )
    response = await chat_completion(prompt)
    if not response:
        return _fallback_parse(positions, cp_text), positions
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError as e:
        logger.error("cp_parser.invalid_json", error=str(e))
        return _fallback_parse(positions, cp_text), positions
    return parsed, positions

def _fallback_parse(positions: List[TenderPosition], cp_text: str) -> dict:
    parsed_positions = []
    for p in positions:
        parsed_positions.append(
            {
                "tender_position_number": p.position_number,
                "supplier_name": p.name,
                "match_type": "not_found",
                "price_per_unit": None,
                "quantity_available": None,
                "delivery_days": None,
                "nds_included": True,
                "nds_rate": 20,
                "notes": "",
            }
        )
    return {
        "positions": parsed_positions,
        "delivery_terms": {},
        "payment_terms": {},
        "valid_until": None,
    }

async def save_parsed_cp(
    db: AsyncSession,
    commercial_offer: CommercialOffer,
    parsed: dict,
    tender: Tender,
) -> None:
    """Сохраняет позиции КП и пересчитывает маржу."""
    result = await db.execute(
        select(TenderPosition).where(TenderPosition.tender_id == tender.id)
    )
    tender_positions = list(result.scalars().all())
    tender.positions = tender_positions

    # Валидация структуры
    raw_positions = parsed.get("positions", [])
    if not isinstance(raw_positions, list) or len(raw_positions) == 0:
        commercial_offer.status = "ERROR"
        commercial_offer.clarification_needed = True
        commercial_offer.clarification_items = ["Не удалось извлечь позиции из КП"]
        commercial_offer.parsed_at = datetime.now(timezone.utc)
        logger.error("cp.parsed_error", offer_id=str(commercial_offer.id), tender_id=str(tender.id))
        return

    new_positions = []
    total_cost = Decimal("0")
    coverage_count = 0
    total_positions = len(tender_positions)
    clarification_items = []

    for item in raw_positions:
        pos_num = item.get("tender_position_number")
        tender_pos = next((tp for tp in tender_positions if tp.position_number == pos_num), None)
        price = item.get("price_per_unit")
        try:
            price_dec = Decimal(str(price)) if price is not None else None
        except (InvalidOperation, TypeError):
            price_dec = None
        quantity = tender_pos.quantity if tender_pos else None
        total_price = price_dec * quantity if price_dec and quantity else None
        if price_dec and tender_pos:
            coverage_count += 1
        if total_price:
            total_cost += total_price
        position = OfferPosition(
            commercial_offer_id=commercial_offer.id,
            tender_position_id=tender_pos.id if tender_pos else None,
            supplier_name=item.get("supplier_name", ""),
            match_type=item.get("match_type", "not_found"),
            match_confidence=item.get("match_confidence"),
            price_per_unit=price_dec,
            quantity_available=item.get("quantity_available"),
            delivery_days=item.get("delivery_days"),
            nds_included=item.get("nds_included", True),
            nds_rate=item.get("nds_rate", 20),
            total_price=total_price,
            notes=item.get("notes", ""),
        )
        new_positions.append(position)

    commercial_offer.positions = new_positions
    delivery_cost = Decimal("0")
    delivery_terms = parsed.get("delivery_terms", {})
    if delivery_terms and delivery_terms.get("delivery_cost"):
        try:
            delivery_cost = Decimal(str(delivery_terms["delivery_cost"]))
        except (InvalidOperation, TypeError):
            delivery_cost = Decimal("0")
    total_cost_with_delivery = total_cost + delivery_cost

    security_bid = None
    security_contract = None
    if tender.structured_data and tender.structured_data.get("requirements"):
        security_bid = tender.structured_data["requirements"].get("security_bid")
        security_contract = tender.structured_data["requirements"].get("security_contract")
    try:
        sec_bid = Decimal(str(security_bid)) if security_bid else Decimal("0")
        sec_contract = Decimal(str(security_contract)) if security_contract else Decimal("0")
    except (InvalidOperation, TypeError):
        sec_bid = Decimal("0")
        sec_contract = Decimal("0")
    total_cost_with_all = total_cost_with_delivery + sec_bid + sec_contract
    nmck = tender.nmck or Decimal("0")
    margin_abs = nmck - total_cost_with_all if nmck else Decimal("0")
    margin_pct = (margin_abs / nmck * 100) if nmck else 0

    commercial_offer.total_cost = total_cost
    commercial_offer.delivery_cost = delivery_cost
    commercial_offer.total_cost_with_delivery = total_cost_with_delivery
    commercial_offer.total_cost_with_all = total_cost_with_all
    commercial_offer.margin_absolute = margin_abs
    commercial_offer.margin_percent = float(margin_pct)
    coverage = (coverage_count / total_positions * 100) if total_positions else 0
    commercial_offer.coverage = coverage
    commercial_offer.status = "FULL" if coverage == 100 else ("PARTIAL" if coverage > 0 else "NONE")

    if any(pp.get("price_per_unit") is None for pp in raw_positions):
        clarification_items.append("Не указана цена по некоторым позициям")
    if not delivery_terms or not delivery_terms.get("delivery_days"):
        clarification_items.append("Не указаны сроки поставки")
    if not parsed.get("payment_terms"):
        clarification_items.append("Не указаны условия оплаты")
    if coverage < 100:
        clarification_items.append("Покрытие позиций менее 100%")
    commercial_offer.clarification_needed = bool(clarification_items)
    commercial_offer.clarification_items = clarification_items
    commercial_offer.parsed_at = datetime.now(timezone.utc)
    logger.info("cp.parsed", offer_id=str(commercial_offer.id), tender_id=str(tender.id), status=commercial_offer.status, coverage=commercial_offer.coverage)