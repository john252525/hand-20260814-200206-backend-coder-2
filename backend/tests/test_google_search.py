import pytest
from unittest.mock import AsyncMock, patch

from app.services.google_search_service import google_search
from app.services.supplier_search_service import search_suppliers_combined


@pytest.mark.asyncio
async def test_google_search_no_keys(setup_db):
    from app.core.config import settings
    # Если ключи не заданы — возвращаем пустой список
    old_key = settings.google_search_api_key
    old_cx = settings.google_search_cx
    settings.google_search_api_key = ""
    settings.google_search_cx = ""
    result = await google_search("test")
    assert result == []
    settings.google_search_api_key = old_key
    settings.google_search_cx = old_cx


@pytest.mark.asyncio
async def test_google_search_mock(setup_db):
    from app.core.config import settings
    old_key = settings.google_search_api_key
    old_cx = settings.google_search_cx
    settings.google_search_api_key = "test-key"
    settings.google_search_cx = "test-cx"

    mock_items = [
        {"title": "ООО Компьютерный мир", "link": "https://compworld.ru", "snippet": "..."},
        {"title": "ТехноТрейд", "link": "https://techno-trade.ru", "snippet": "..."},
    ]
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"items": mock_items}
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        result = await google_search("компьютер")
        assert len(result) == 2

    settings.google_search_api_key = old_key
    settings.google_search_cx = old_cx


@pytest.mark.asyncio
async def test_combined_search_dedup(setup_db):
    from app.core.database import AsyncSessionLocal
    from app.models import Supplier
    from app.services.supplier_search_service import search_suppliers_combined

    async with AsyncSessionLocal() as db:
        supplier = Supplier(name="ООО Компьютерный мир", email="sales@compworld.ru", website="https://compworld.ru")
        db.add(supplier)
        await db.commit()

    # Эмулируем внешние результаты с тем же email/доменом
    with patch(
        "app.services.supplier_search_service.search_suppliers_external",
        new_callable=AsyncMock,
    ) as mock_external:
        mock_external.return_value = [
            {"name": "Компьютерный мир", "email": "sales@compworld.ru", "website": "https://compworld.ru", "source": "google", "snippet": ""},
        ]
        result = await search_suppliers_combined(db, "компьютер")
        # Должен остаться только внутренний поставщик
        assert len(result) == 1
        assert result[0]["source"] == "internal_db"
