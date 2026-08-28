from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Decision, Tender, TenderSource, TenderPosition, Webhook
from app.services.ml_service import collect_training_data, train_model
from app.services.webhook_dispatcher import send_webhook_event


@pytest.mark.asyncio
async def test_collect_training_data(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Test", nmck=Decimal("1000"), status="APPROVED")
        db.add(tender)
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Позиция", quantity=1, unit="шт"))
        db.add(Decision(tender_id=tender.id, decision="APPROVED", reason="ok"))
        await db.commit()

        data = await collect_training_data(db)
        assert len(data) >= 1
        assert data[0]["positions_count"] >= 1

        metrics = await train_model(db)
        assert metrics["samples"] >= 1
        assert metrics["accuracy"] is not None or metrics.get("note") == "Not enough data"


@pytest.mark.asyncio
async def test_webhook_dispatcher_no_hooks(setup_db):
    await send_webhook_event("test.event", {"data": 1})


@pytest.mark.asyncio
async def test_webhook_dispatcher_mock(setup_db):
    async with AsyncSessionLocal() as db:
        db.add(Webhook(url="https://example.com", events=["test.event"], secret="secret"))
        await db.commit()

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        await send_webhook_event("test.event", {"data": 1})

    async with AsyncSessionLocal() as db:
        wh = (await db.execute(select(Webhook))).scalar_one()
        assert wh.last_status == "success"
        assert wh.retry_count == 0
