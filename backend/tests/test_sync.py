import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource
from app.workers.sync_tenders import _sync


@pytest.mark.asyncio
async def test_sync_tenders_mock(setup_db):
    # Создаём источник
    async with AsyncSessionLocal() as db:
        source = TenderSource(
            name="ГосПлан",
            type="aggregator_api",
            api_url="https://v2test.gosplan.info/fz44/purchases"
        )
        db.add(source)
        await db.commit()
        await db.refresh(source)
        source_id = source.id

    # Мокаем ответ ГосПлан API
    items = [
        {
            "purchase_number": "123",
            "object_info": "Поставка ноутбуков",
            "max_price": 1500000,
            "currency_code": "RUB",
            "published_at": "2026-01-01T00:00:00Z",
            "collecting_finished_at": "2026-02-01T00:00:00Z",
            "customers": ["7712345678"],
        }
    ]

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = items
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        await _sync(str(source_id))

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Tender))
        tenders = result.scalars().all()
        assert len(tenders) == 1
        assert tenders[0].source_tender_id == "123"
        assert tenders[0].customer_inn == "7712345678"

        source = await db.get(TenderSource, source_id)
        assert source.last_sync_status == "success"
        assert source.last_sync_at is not None
