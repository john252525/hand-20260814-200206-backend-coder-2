import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import LotSupplier, Supplier, Tender, TenderSource, Task
from app.workers.send_communications import _send_cp_requests


@pytest.mark.asyncio
async def test_send_cp_requests_filters_by_supplier_ids(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1000"))
        supplier1 = Supplier(name="Supplier1", email="s1@test.com")
        supplier2 = Supplier(name="Supplier2", email="s2@test.com")
        db.add_all([tender, supplier1, supplier2])
        await db.flush()
        ls1 = LotSupplier(tender_id=tender.id, supplier_id=supplier1.id, status="PENDING")
        ls2 = LotSupplier(tender_id=tender.id, supplier_id=supplier2.id, status="PENDING")
        db.add_all([ls1, ls2])
        await db.commit()
        tender_id = tender.id
        supplier1_id = supplier1.id

    # Отправляем только supplier1
    await _send_cp_requests(str(tender_id), None, [str(supplier1_id)])

    # Проверяем, что ls1 стал CP_REQUESTED, ls2 остался PENDING
    async with AsyncSessionLocal() as db:
        ls1 = (await db.execute(select(LotSupplier).where(LotSupplier.supplier_id == supplier1_id))).scalar_one()
        assert ls1.status == "CP_REQUESTED"
        ls2 = (await db.execute(select(LotSupplier).where(LotSupplier.supplier_id == supplier2.id))).scalar_one()
        assert ls2.status == "PENDING"
