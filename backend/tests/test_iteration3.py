import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource, Task, TenderStatusHistory, Supplier
from app.workers.sync_tenders import _sync
from app.services.llm_service import chat_completion
from app.services.supplier_search_service import search_suppliers_external, _infer_type

@pytest.mark.asyncio
async def test_llm_retry_on_error(setup_db, monkeypatch):
    """Проверяем, что chat_completion делает 3 попытки и возвращает результат."""
    from openai import AsyncOpenAI
    
    class FakeCompletions:
        def __init__(self):
            self.calls = 0
        async def create(self, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise Exception("temporary network error")
            resp = MagicMock()
            resp.choices[0].message.content = "ok"
            return resp

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = MagicMock()
            self.chat.completions = FakeCompletions()

    # Патчим AsyncOpenAI, чтобы вернуть фейковый клиент
    monkeypatch.setattr("app.services.llm_service.AsyncOpenAI", FakeClient)
    # Устанавливаем ключ, чтобы функция не вышла рано
    from app.core.config import settings
    old_key = settings.llm_api_key
    settings.llm_api_key = "test-key"
    try:
        result = await chat_completion("test")
        assert result == "ok"
    finally:
        settings.llm_api_key = old_key

@pytest.mark.asyncio
async def test_sync_archives_missing_tender(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="ГосПлан", type="aggregator_api", api_url="https://v2test.gosplan.info/fz44/purchases")
        db.add(source)
        await db.flush()
        # Тендер с missing_count=1
        t1 = Tender(source_id=source.id, source_tender_id="old-1", title="Старый", status="NEW", missing_count=1)
        # Тендер, который встретится в выдаче
        t2 = Tender(source_id=source.id, source_tender_id="new-1", title="Новый", status="NEW", missing_count=0)
        db.add_all([t1, t2])
        await db.commit()
        source_id = source.id
    # Мокаем API, возвращаем только new-1
    items = [{"purchase_number": "new-1", "object_info": "Новый", "max_price": 100}]
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = items
    mock_resp.raise_for_status = lambda: None
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        await _sync(str(source_id))
    async with AsyncSessionLocal() as db:
        t1 = (await db.execute(select(Tender).where(Tender.source_tender_id == "old-1"))).scalar_one()
        t2 = (await db.execute(select(Tender).where(Tender.source_tender_id == "new-1"))).scalar_one()
        assert t1.missing_count == 2
        assert t1.status == "ARCHIVED"
        # История статуса должна содержать ARCHIVED
        hist = (await db.execute(select(TenderStatusHistory).where(TenderStatusHistory.tender_id == t1.id, TenderStatusHistory.status == "ARCHIVED"))).scalar_one_or_none()
        assert hist is not None
        assert t2.missing_count == 0

@pytest.mark.asyncio
async def test_supplier_search_infers_type(setup_db):
    assert _infer_type("ООО Завод производитель", "") == "manufacturer"
    assert _infer_type("Оптовый поставщик", "") == "wholesaler"
    assert _infer_type("Магазин техники", "") == "retail"
    assert _infer_type("Официальный дистрибьютор", "") == "distributor"
    assert _infer_type("Непонятная компания", "") == "unknown"

@pytest.mark.asyncio
async def test_supplier_created_logging(client, api_token, setup_db):
    # Проверяем, что создание поставщика работает (логирование не тестируем напрямую)
    resp = await client.post(
        "/api/v1/suppliers",
        json={"name": "ООО Тест", "email": "test@example.com"},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 201