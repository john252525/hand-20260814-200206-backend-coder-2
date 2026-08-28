from unittest.mock import AsyncMock, patch
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import LotSupplier, Supplier, Tender, TenderSource
from app.workers.process_incoming import _process_incoming_email


@pytest.mark.asyncio
async def test_decline_sets_no_suppliers_found(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ненужный тендер", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="sales@supplier.ru")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="CP_REQUESTED")
        db.add(ls)
        await db.commit()
        tender_id = tender.id

    with patch(
        "app.workers.process_incoming.classify_email",
        new_callable=AsyncMock,
        return_value="decline",
    ):
        await _process_incoming_email({"message_id": "msg1", "from_": "sales@supplier.ru", "subject": "Отказ", "body": "не работаем", "attachments": []})

    async with AsyncSessionLocal() as db:
        ls = (await db.execute(select(LotSupplier).where(LotSupplier.tender_id == tender_id))).scalar_one()
        assert ls.status == "DECLINED"
        tender = await db.get(Tender, tender_id)
        assert tender.status == "NO_SUPPLIERS_FOUND"
