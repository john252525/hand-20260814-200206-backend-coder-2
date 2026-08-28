import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import (
    Communication, LotSupplier, Supplier, Tender, TenderSource,
    CommercialOffer, Task,
)

@pytest.mark.asyncio
async def test_supplier_communications(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="PENDING")
        db.add(ls)
        await db.flush()
        comm = Communication(
            lot_supplier_id=ls.id, tender_id=tender.id, direction="outgoing", channel="email",
            subject="Test", body_text="Body", message_type="manual",
        )
        db.add(comm)
        await db.commit()
        supplier_id = supplier.id
    resp = await client.get(f"/api/v1/suppliers/{supplier_id}/communications", headers={"X-API-Token": api_token})
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1

@pytest.mark.asyncio
async def test_merge_suppliers(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        s1 = Supplier(name="S1", email="s1@test.com")
        s2 = Supplier(name="S2", email="s2@test.com")
        db.add_all([s1, s2])
        await db.commit()
        s1_id, s2_id = s1.id, s2.id
    resp = await client.post(
        "/api/v1/suppliers/merge",
        json={"primary_id": str(s1_id), "secondary_id": str(s2_id)},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 200
    async with AsyncSessionLocal() as db:
        s1 = await db.get(Supplier, s1_id)
        s2 = await db.get(Supplier, s2_id)
        assert s2.is_active is False

@pytest.mark.asyncio
async def test_communications_send(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="PENDING")
        db.add(ls)
        await db.commit()
        tender_id, supplier_id = tender.id, supplier.id
    resp = await client.post(
        f"/api/v1/tenders/{tender_id}/communications/send",
        json={"supplier_id": str(supplier_id), "subject": "Hello", "body": "Test"},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 201

@pytest.mark.asyncio
async def test_negotiation_status(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        db.add(LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="CP_REQUESTED"))
        await db.commit()
        tender_id = tender.id
    resp = await client.get(f"/api/v1/tenders/{tender_id}/negotiation-status", headers={"X-API-Token": api_token})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "NOT_STARTED"

@pytest.mark.asyncio
async def test_supplier_search_results_empty(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1000"))
        db.add(tender)
        await db.commit()
        tender_id = tender.id
    resp = await client.get(f"/api/v1/tenders/{tender_id}/supplier-search-results", headers={"X-API-Token": api_token})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "NOT_SEARCHED"
