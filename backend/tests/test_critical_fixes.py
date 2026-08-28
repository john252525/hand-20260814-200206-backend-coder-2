import pytest
from decimal import Decimal
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource

@pytest.mark.asyncio
async def test_tenders_stats_endpoint(client, api_token, setup_db):
    # Создаём тендер для статистики
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="stats-1", title="Test", nmck=Decimal("1000"), status="NEW")
        db.add(tender)
        await db.commit()
    resp = await client.get("/api/v1/tenders/stats", headers={"X-API-Token": api_token})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["total"] >= 1

@pytest.mark.asyncio
async def test_negotiate_worker_import():
    # Проверяем, что воркер переговоров импортируется без ошибок
    import app.workers.negotiate  # noqa: F401