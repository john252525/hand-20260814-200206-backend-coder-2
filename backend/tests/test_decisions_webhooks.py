import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models import (
    Decision,
    CommercialOffer,
    Communication,
    LotSupplier,
    Supplier,
    Tender,
    TenderPosition,
    TenderSource,
    Webhook,
)


@pytest.mark.asyncio
async def test_create_webhook_and_test(client, api_token, setup_db):
    resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["test"], "secret": "secret"},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 201
    hook_id = resp.json()["data"]["id"]

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        test_resp = await client.post(f"/api/v1/webhooks/{hook_id}/test", headers={"X-API-Token": api_token})
        assert test_resp.status_code == 200
        assert test_resp.json()["data"]["signature"]


@pytest.mark.asyncio
async def test_decision_approve_flow(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1500000"), status="READY_FOR_DECISION")
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Ноутбук", quantity=10, unit="шт"))
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="RESPONDED")
        db.add(ls)
        await db.flush()
        comm = Communication(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            direction="incoming",
            channel="email",
            subject="КП",
            body_text="...",
            message_type="cp_response",
        )
        db.add(comm)
        await db.flush()
        offer = CommercialOffer(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            source_communication_id=comm.id,
            status="FULL",
            coverage=100.0,
            total_cost_with_all=Decimal("1000000"),
            margin_absolute=Decimal("500000"),
            margin_percent=33.3,
            raw_text_snippet="...",
        )
        db.add(offer)
        await db.commit()
        tender_id = tender.id
        supplier_id = supplier.id
        offer_id = offer.id

    resp = await client.post(
        f"/api/v1/decisions/{tender_id}/approve",
        json={"chosen_supplier_id": str(supplier_id), "chosen_offer_id": str(offer_id), "comment": "ok"},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["decision"] == "APPROVED"

    async with AsyncSessionLocal() as db:
        tender = await db.get(Tender, tender_id, options=[selectinload(Tender.positions)])
        assert tender.status == "APPROVED"

        decision = (await db.execute(select(Decision).where(Decision.tender_id == tender_id))).scalar_one()
        assert decision.decision == "APPROVED"
        assert decision.risk_level_at_decision in ("LOW", "MEDIUM", "HIGH")
        assert decision.margin_at_decision == Decimal("500000")


@pytest.mark.asyncio
async def test_decision_reject_flow_with_positions(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="124", title="Ненужный", nmck=Decimal("1000"), status="READY_FOR_DECISION")
        db.add(tender)
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Ненужная позиция", quantity=1, unit="шт"))
        await db.commit()
        tender_id = tender.id

    resp = await client.post(
        f"/api/v1/decisions/{tender_id}/reject",
        json={"reason": "low_margin", "comment": "Маржа низкая"},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["decision"] == "REJECTED"

    async with AsyncSessionLocal() as db:
        tender = await db.get(Tender, tender_id)
        assert tender.status == "REJECTED"
        decision = (await db.execute(select(Decision).where(Decision.tender_id == tender_id))).scalar_one()
        assert decision.risk_level_at_decision is not None


@pytest.mark.asyncio
async def test_list_decisions(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="125", title="Test", nmck=Decimal("1000"), status="APPROVED")
        db.add(tender)
        await db.flush()
        db.add(Decision(
            tender_id=tender.id,
            decision="APPROVED",
            reason="ok",
        ))
        await db.commit()

    resp = await client.get("/api/v1/decisions?status=APPROVED", headers={"X-API-Token": api_token})
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


@pytest.mark.asyncio
async def test_request_info(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="126", title="Test", nmck=Decimal("1000"), status="READY_FOR_DECISION")
        db.add(tender)
        await db.commit()
        tender_id = tender.id

    resp = await client.post(
        f"/api/v1/decisions/{tender_id}/request-info",
        json={"instructions": "Уточнить цену доставки"},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 202
    assert "task_id" in resp.json()["data"]


@pytest.mark.asyncio
async def test_update_delete_webhook(client, api_token, setup_db):
    resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["test"], "secret": "secret"},
        headers={"X-API-Token": api_token},
    )
    hook_id = resp.json()["data"]["id"]

    upd = await client.patch(
        f"/api/v1/webhooks/{hook_id}",
        json={"is_active": False},
        headers={"X-API-Token": api_token},
    )
    assert upd.status_code == 200

    del_resp = await client.delete(f"/api/v1/webhooks/{hook_id}", headers={"X-API-Token": api_token})
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True
