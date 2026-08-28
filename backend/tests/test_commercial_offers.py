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


@pytest.mark.asyncio
async def test_list_commercial_offers_with_supplier_filter(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="CP_REQUESTED")
        db.add(ls)
        await db.flush()
        comm = Communication(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            direction="incoming",
            channel="email",
            subject="КП",
            body_text="Тест",
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
        supplier_id = supplier.id

    response = await client.get(
        f"/api/v1/commercial-offers?supplier_id={supplier_id}",
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 1


@pytest.mark.asyncio
async def test_reparse_offer_returns_202(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="CP_REQUESTED")
        db.add(ls)
        await db.flush()
        comm = Communication(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            direction="incoming",
            channel="email",
            subject="КП",
            body_text="Тест",
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

    response = await client.post(
        f"/api/v1/commercial-offers/{offer_id}/reparse",
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 202
    assert "task_id" in response.json()["data"]
