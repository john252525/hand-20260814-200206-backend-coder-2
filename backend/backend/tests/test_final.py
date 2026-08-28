import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import (
    Tender, TenderSource, Category, Task, Supplier,
)

@pytest.mark.asyncio
async def test_list_tasks(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        task = Task(task_type="TEST", status="PENDING")
        db.add(task)
        await db.commit()
    resp = await client.get("/api/v1/tasks", headers={"X-API-Token": api_token})
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 1

@pytest.mark.asyncio
async def test_delete_tender_source(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Delete", type="aggregator_api", api_url="https://del")
        db.add(source)
        await db.commit()
        source_id = source.id
    resp = await client.delete(f"/api/v1/tender-sources/{source_id}", headers={"X-API-Token": api_token})
    assert resp.status_code == 200
    async with AsyncSessionLocal() as db:
        source = await db.get(TenderSource, source_id)
        assert source.is_active is False

@pytest.mark.asyncio
async def test_bulk_import_categories(client, api_token, setup_db):
    resp = await client.post(
        "/api/v1/categories/bulk-import",
        json=[{"name": "Cat1", "description": "Desc1"}],
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 202
    assert "task_id" in resp.json()["data"]

@pytest.mark.asyncio
async def test_negotiation_status_not_started(client, api_token, setup_db):
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
