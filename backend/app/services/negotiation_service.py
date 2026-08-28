from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Communication, LotSupplier, Task, CommercialOffer, Supplier
from app.services.settings_service import get_section
from app.services.llm_service import chat_completion


async def generate_clarification_email(
    db: AsyncSession,
    lot_supplier: LotSupplier,
    offer: CommercialOffer,
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
    subject = subject_tpl.replace("{lot_name}", str(offer.tender_id))
    body = body_tpl.replace("{clarification_items}", items)
    body = body.replace("{company_signature}", company_signature)
    return subject, body


async def generate_discount_email(
    db: AsyncSession,
    lot_supplier: LotSupplier,
    offer: CommercialOffer,
    competitive_prices: dict,
) -> tuple[str, str]:
    """Генерирует письмо с запросом скидки на основе реальных цен конкурентов."""
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

    # Формируем список позиций, где конкуренты дешевле
    lines = []
    for pos in offer.positions:
        if pos.tender_position_id in competitive_prices:
            comp_price = competitive_prices[pos.tender_position_id]
            if pos.price_per_unit and comp_price < pos.price_per_unit:
                lines.append(f"- Позиция {pos.supplier_name}: наша цена {pos.price_per_unit}, конкурент {comp_price}")
    if not lines:
        lines.append("- По ряду позиций конкуренты предлагают более низкие цены")
    discount_positions = "\n".join(lines)

    subject = subject_tpl.replace("{lot_name}", str(offer.tender_id))
    body = body_tpl.replace("{discount_positions}", discount_positions)
    body = body.replace("{company_signature}", company_signature)
    return subject, body


async def request_clarification(
    db: AsyncSession,
    lot_supplier: LotSupplier,
    offer: CommercialOffer,
) -> Communication:
    subject, body = await generate_clarification_email(db, lot_supplier, offer)
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
) -> Communication:
    subject, body = await generate_discount_email(db, lot_supplier, offer, competitive_prices)
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
