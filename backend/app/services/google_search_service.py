from typing import List, Dict, Any

import httpx

from app.core.config import settings


async def google_search(query: str, num: int = 10) -> List[Dict[str, Any]]:
    """Поиск через Google Custom Search API.
    Если ключи не настроены, возвращает пустой список.
    """
    if not settings.google_search_api_key or not settings.google_search_cx:
        return []
    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": settings.google_search_api_key,
            "cx": settings.google_search_cx,
            "q": query,
            "num": min(num, settings.google_search_max_results or 10),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("items", [])
    except Exception:
        return []
