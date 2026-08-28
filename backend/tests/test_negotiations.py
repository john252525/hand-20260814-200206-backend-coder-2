from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import CommercialOffer, Communication, LotSupplier, Supplier, Tender, TenderPosition, TenderSource


@pytest.mark.asyncio
async def test_negotiate_clarification(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1500000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Ноутбук", quantity=10, unit="шт"))
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="RESPONDED")
        db.add(ls)
        await db.flush()
        offer = CommercialOffer(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            status="PARTIAL",
            coverage=50.0,
            clarification_needed=True,
            clarification_items=["Не указана цена"],
            raw_text_snippet="...",
        )
        db.add(offer)
        await db.commit()
        ls_id = ls.id

    resp = await client.post(
        f"/api/v1/negotiations/tenders/{tender.id}/negotiate",
        json={"action": "request_clarification", "target_supplier_ids": [str(supplier.id)]},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 202
    assert resp.json()["data"]["processed"] == 1

    async with AsyncSessionLocal() as db:
        comm = (await db.execute(select(Communication).where(Communication.message_type == "clarification"))).scalar_one()
        assert comm.direction == "outgoing"
        assert comm.lot_supplier_id == ls_id
        ls = await db.get(LotSupplier, ls_id)
        assert ls.status == "NEGOTIATING"
