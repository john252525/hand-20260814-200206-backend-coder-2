import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Category, Tender, TenderSource
from app.workers.process_tender import _process


@pytest.mark.asyncio
async def test_end_to_end(setup_db):
    # Создаём источник и категорию
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="ГосПлан", type="aggregator_api", api_url="https://v2test.gosplan.info/fz44/purchases")
        db.add(source)
        await db.flush()
        category = Category(name="Компьютеры", description="Ноутбуки, ПК", keywords=["ноутбук", "компьютер"])
        db.add(category)
        await db.commit()
        source_id = source.id
        category_id = category.id

    # Создаём тендер вручную (мок реального ответа API)
    async with AsyncSessionLocal() as db:
        source = await db.get(TenderSource, source_id)
        tender = Tender(
            source_id=source.id,
            source_tender_id="test-123",
            title="Поставка ноутбуков HP",
            description="Ноутбуки для офиса",
            nmck=Decimal("1500000"),
        )
        db.add(tender)
        await db.commit()
        tender_id = tender.id

    # Обрабатываем тендер
    await _process(str(tender_id))

    # Проверяем результат
    async with AsyncSessionLocal() as db:
        tender = await db.get(Tender, tender_id)
        assert tender.status == "SCORED"
        assert tender.score is not None
        assert tender.matched_category_id is not None
