from datetime import datetime, timezone
from typing import Optional, Dict, List
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models import Communication, LotSupplier, Task, CommercialOffer, Supplier
from app.services.settings_service import get_section
from app.services.llm_service import chat_completion

logger = structlog.get_logger(__name__)

NEGOTIATION_SYSTEM_PROMPT = """Ты — профессиональный менеджер по закупкам компании {company_name}.
Твоя задача — получить наилучшие условия от поставщиков.
Правила:
- Вежливый, деловой тон.
- Не ври — не ссылайся на несуществующих конкурентов с выдуманными ценами.
- Указывай конкретные позиции и цены (только те, что реально получены от других поставщиков).
- Не называй имена конкурентов.
- Подчёркивай объём закупки и потенциал долгосрочного сотрудничества.
- Если поставщик отказывает третий раз — прекрати переговоры с благодарностью.
"""

async def _get_conversation_history(db: AsyncSession, lot_supplier_id: str, limit: int = 10) -> List[str]:
    result = await db.execute(
        select(Communication)
        .where(Communication.lot_supplier_id == lot_supplier_id)
        .order_by(Communication.created_at.desc())
        .limit(limit)
    )
    comms = result.scalars().all()
    return [f"{'Входящее' if c.direction == 'incoming' else 'Исходящее'} ({c.subject}):\n{c.body_text[:500]}" for c in comms]

async def _generate_with_llm(db: AsyncSession, template_type: str, context: dict) -> Optional[tuple[str, str]]:
    from app.core.config import settings
    if not settings.llm_api_key:
        return None
    templates = await get_section(db, "templates")
    template = templates.get(template_type, {})
    subject_tpl = template.get("subject", "")
    body_tpl = template.get("body", "")
    company = await get_section(db, "company")
    company_name = company.get("legal_name", "")
    history = context.get("history", [])
    history_text = "\n".join(history) if history else "Нет истории."
    prompt = f"""Сгенерируй письмо поставщику на основе шаблона и контекста.

Шаблон темы: {subject_tpl}
Шаблон тела: {body_tpl}

Контекст:
{context.get('data', '')}

История переписки:
{history_text}

Требования:
- Замени плейсхолдеры в шаблоне на реальные данные из контекста.
- Используй историю для учёта предыдущих договорённостей.
- Ответ строго в формате JSON: {{"subject": "...", "body": "..."}}
"""
    system = NEGOTIATION_SYSTEM_PROMPT.format(company_name=company_name)
    response = await chat_completion(prompt, system=system)
    if not response:
        return None
    try:
        import json
        data = json.loads(response)
        return data.get("subject", ""), data.get("body", "")
    except Exception:
        return None

async def generate_clarification_email(
    db: AsyncSession,
    lot_supplier: LotSupplier,
    offer: CommercialOffer,
    custom_instructions: Optional[str] = None,
) -> tuple[str, str]:
    templates = await get_section(db, "templates")
    template = templates.get("clarification", {})
    subject_tpl = template.get("subject", "Уточнение по КП: {lot_name}")
    body_tpl = template.get("body", "Добрый день!\n\nБлагодарим за предоставленное КП. Просим уточнить: {clarification_items}\n\n{company_signature}")
    company = await get_section(db, "company")
    company_signature = (
        f"{company.get('email_signature', '')}\n"
        f"{company.get('contact_person', '')}\n"
        f"{company.get('legal_name', '')}\n"
        f"{company.get('contact_phone', '')}\n"
        f"{company.get('contact_email', '')}"
    ).strip()
    items = "\n".join(f"- {item}" for item in offer.clarification_items)
    if custom_instructions:
        items += f"\n\nДополнительно: {custom_instructions}"
    subject = subject_tpl.replace("{lot_name}", str(offer.tender_id))
    body = body_tpl.replace("{clarification_items}", items)
    body = body.replace("{company_signature}", company_signature)

    history = await _get_conversation_history(db, str(lot_supplier.id))
    context = {"data": f"Тендер: {offer.tender_id}\nПозиции для уточнения: {items}", "history": history}
    llm_result = await _generate_with_llm(db, "clarification", context)
    if llm_result:
        subject, body = llm_result
    logger.info("negotiation.step", action="clarification", lot_supplier_id=str(lot_supplier.id), tender_id=str(lot_supplier.tender_id))
    return subject, body

async def generate_discount_email(
    db: AsyncSession,
    lot_supplier: LotSupplier,
    offer: CommercialOffer,
    competitive_prices: dict,
    custom_instructions: Optional[str] = None,
) -> tuple[str, str]:
    templates = await get_section(db, "templates")
    template = templates.get("discount_request", {})
    subject_tpl = template.get("subject", "Запрос улучшения условий: {lot_name}")
    body_tpl = template.get("body", "Добрый день!\n\nБлагодарим за предоставленное КП. Конкуренты предлагают более выгодные условия по позициям:\n\n{discount_positions}\n\n{company_signature}")
    company = await get_section(db, "company")
    company_signature = (
        f"{company.get('email_signature', '')}\n"
        f"{company.get('contact_person', '')}\n"
        f"{company.get('legal_name', '')}\n"
        f"{company.get('contact_phone', '')}\n"
        f"{company.get('contact_email', '')}"
    ).strip()
    lines = []
    for pos in offer.positions:
        if pos.tender_position_id in competitive_prices:
            comp_price = competitive_prices[pos.tender_position_id]
            if pos.price_per_unit and comp_price < pos.price_per_unit:
                lines.append(f"- Позиция {pos.supplier_name}: наша цена {pos.price_per_unit}, конкурент {comp_price}")
    if not lines:
        lines.append("- По ряду позиций конкуренты предлагают более низкие цены")
    discount_positions = "\n".join(lines)
    if custom_instructions:
        discount_positions += f"\n\nДополнительно: {custom_instructions}"
    subject = subject_tpl.replace("{lot_name}", str(offer.tender_id))
    body = body_tpl.replace("{discount_positions}", discount_positions)
    body = body.replace("{company_signature}", company_signature)

    history = await _get_conversation_history(db, str(lot_supplier.id))
    context = {"data": f"Тендер: {offer.tender_id}\nПозиции для снижения цен: {discount_positions}\nКонкурентные цены: {competitive_prices}", "history": history}
    llm_result = await _generate_with_llm(db, "discount_request", context)
    if llm_result:
        subject, body = llm_result
    logger.info("negotiation.step", action="discount_request", lot_supplier_id=str(lot_supplier.id), tender_id=str(lot_supplier.tender_id))
    return subject, body

async def request_clarification(
    db: AsyncSession,
    lot_supplier: LotSupplier,
    offer: CommercialOffer,
    custom_instructions: Optional[str] = None,
) -> Communication:
    subject, body = await generate_clarification_email(db, lot_supplier, offer, custom_instructions)
    comm = Communication(
        lot_supplier_id=lot_supplier.id,
        tender_id=lot_supplier.tender_id,
        direction="outgoing",
        channel="email",
        subject=subject,
        body_text=body,
        message_type="clarification",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(comm)
    lot_supplier.status = "NEGOTIATING"
    await db.flush()
    return comm

async def request_discount(
    db: AsyncSession,
    lot_supplier: LotSupplier,
    offer: CommercialOffer,
    competitive_prices: dict,
    custom_instructions: Optional[str] = None,
) -> Communication:
    subject, body = await generate_discount_email(db, lot_supplier, offer, competitive_prices, custom_instructions)
    comm = Communication(
        lot_supplier_id=lot_supplier.id,
        tender_id=lot_supplier.tender_id,
        direction="outgoing",
        channel="email",
        subject=subject,
        body_text=body,
        message_type="discount_request",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(comm)
    lot_supplier.status = "NEGOTIATING"
    await db.flush()
    return comm

async def get_competitive_prices(db: AsyncSession, tender_id, except_offer_id) -> Dict:
    offers_result = await db.execute(
        select(CommercialOffer)
        .where(CommercialOffer.tender_id == tender_id, CommercialOffer.id != except_offer_id)
        .options(selectinload(CommercialOffer.positions))
    )
    competitive = {}
    for offer in offers_result.scalars().all():
        for pos in offer.positions:
            if pos.tender_position_id and pos.price_per_unit:
                current = competitive.get(pos.tender_position_id)
                if current is None or pos.price_per_unit < current:
                    competitive[pos.tender_position_id] = pos.price_per_unit
    return competitive