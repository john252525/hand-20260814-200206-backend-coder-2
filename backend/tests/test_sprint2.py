import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Communication, LotSupplier, Supplier, Tender, TenderSource


@pytest.mark.asyncio
async def test_create_lot_supplier(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Test", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id)
        db.add(ls)
        await db.commit()
        assert ls.id is not None
        assert ls.status == "PENDING"


@pytest.mark.asyncio
async def test_create_communication(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Test", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id)
        db.add(ls)
        await db.flush()
        comm = Communication(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            direction="outgoing",
            channel="email",
            subject="Test",
            body_text="Body",
        )
        db.add(comm)
        await db.commit()
        assert comm.id is not None


@pytest.mark.asyncio
async def test_suppliers_search_endpoint(client: AsyncClient, api_token: str):
    # Создаем поставщика
    await client.post(
        "/api/v1/suppliers",
        json={"name": "ООО Компьютерный мир", "email": "sales@compworld.ru"},
        headers={"X-API-Token": api_token},
    )
    response = await client.post(
        "/api/v1/suppliers/search",
        json={"query": "компьютер"},
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) >= 1


@pytest.mark.asyncio
async def test_communications_endpoint(client: AsyncClient, api_token: str):
    # Создаем тендер и поставщика
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Test", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id)
        db.add(ls)
        await db.commit()
        ls_id = ls.id

    response = await client.post(
        "/api/v1/communications",
        json={"lot_supplier_id": str(ls_id), "subject": "Test", "body_text": "Body"},
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 201
    assert response.json()["success"] is True
