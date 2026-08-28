import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

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
from app.workers.process_incoming import _process_incoming_email
from app.workers.parse_cp import _parse_cp


@pytest.mark.asyncio
async def test_incoming_email_creates_cp(setup_db):
    # Создаём тендер с позицией, поставщика, lot_supplier
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1500000"))
        supplier = Supplier(name="ООО Компьютерный мир", email="sales@compworld.ru")
        db.add_all([tender, supplier])
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Ноутбук", quantity=10, unit="шт"))
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="CP_REQUESTED")
        db.add(ls)
        await db.commit()
        ls_id = ls.id

    # Мокаем классификатор и celery delay
    with patch(
        "app.workers.process_incoming.classify_email",
        new_callable=AsyncMock,
        return_value="cp_response",
    ), patch(
        "app.workers.process_incoming.parse_cp_task.delay",
        return_value=AsyncMock(id="fake_celery_id"),
    ):
        email_data = {
            "message_id": "test123",
            "from_": "sales@compworld.ru",
            "subject": "КП по ноутбукам",
            "body": "Коммерческое предложение: Ноутбук HP - 100000 руб за шт.",
            "attachments": [],
        }
        await _process_incoming_email(email_data)

    # Проверяем Communication и CommercialOffer
    async with AsyncSessionLocal() as db:
        comm = (await db.execute(select(Communication).where(Communication.external_id == "test123"))).scalar_one()
        assert comm.message_type == "cp_response"
        assert comm.direction == "incoming"

        offer = (await db.execute(select(CommercialOffer).where(CommercialOffer.source_communication_id == comm.id))).scalar_one()
        # Запускаем парсинг напрямую (как это сделал бы воркер)
        await _parse_cp(str(offer.id), None)
        await db.refresh(offer)
        assert offer.status != "PROCESSING"
        assert offer.parsed_at is not None
