import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import (
    CommercialOffer,
    Communication,
    LotSupplier,
    Supplier,
    Tender,
    TenderPosition,
    TenderSource,
)
from app.workers.parse_cp import _parse_cp


@pytest.mark.asyncio
async def test_parse_cp_task_fallback(setup_db):
    # Создаём объекты
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1500000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Ноутбук", quantity=10, unit="шт"))
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="CP_REQUESTED")
        db.add(ls)
        await db.flush()
        comm = Communication(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            direction="incoming",
            channel="email",
            subject="КП",
            body_text="Тест КП",
            message_type="cp_response",
        )
        db.add(comm)
        await db.flush()
        offer = CommercialOffer(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            source_communication_id=comm.id,
            raw_text_snippet="Тест КП",
        )
        db.add(offer)
        await db.commit()
        offer_id = offer.id

    # Вызываем внутреннюю функцию (без Celery, но с полным циклом)
    await _parse_cp(str(offer_id), None)

    # Проверяем, что offer обработан
    async with AsyncSessionLocal() as db:
        offer = await db.get(CommercialOffer, offer_id)
        assert offer.status in ("FULL", "PARTIAL", "NONE")
        assert offer.parsed_at is not None
