import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import LotSupplier, Supplier, Tender, TenderSource


@pytest.mark.asyncio
async def test_confirm_existing_supplier(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Test", nmck=Decimal("1000"))
        supplier = Supplier(name="ООО Ромашка", email="sales@romashka.ru")
        db.add_all([tender, supplier])
        await db.commit()
        tender_id = tender.id
        supplier_id = supplier.id

    resp = await client.post(
        f"/api/v1/tenders/{tender_id}/supplier-search-results/confirm",
        json={"supplier_ids": [str(supplier_id)], "source_by_id": {str(supplier_id): "google"}},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["linked"] == 1

    async with AsyncSessionLocal() as db:
        ls = (await db.execute(select(LotSupplier).where(LotSupplier.tender_id == tender_id))).scalar_one()
        assert ls.supplier_id == supplier_id
        assert ls.source == "google"


@pytest.mark.asyncio
async def test_confirm_new_supplier_and_duplicate(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Test", nmck=Decimal("1000"))
        db.add(tender)
        await db.commit()
        tender_id = tender.id

    # Создаём нового поставщика через confirm
    resp = await client.post(
        f"/api/v1/tenders/{tender_id}/supplier-search-results/confirm",
        json={
            "new_suppliers": [
                {"name": "Новый Поставщик", "email": "new@supplier.ru", "type": "manufacturer", "tags": ["ноутбуки"]}
            ]
        },
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["linked"] == 1

    # Повторный запрос с тем же email должен привязать существующего, а не создать нового
    resp2 = await client.post(
        f"/api/v1/tenders/{tender_id}/supplier-search-results/confirm",
        json={
            "new_suppliers": [
                {"name": "Новый Поставщик 2", "email": "new@supplier.ru"}
            ]
        },
        headers={"X-API-Token": api_token},
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["linked"] == 0  # уже привязан, дубликат не создан

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Supplier).where(Supplier.email == "new@supplier.ru"))
        suppliers = result.scalars().all()
        assert len(suppliers) == 1
