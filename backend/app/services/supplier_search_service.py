from typing import List, Dict, Any
from urllib.parse import urlparse
import httpx
import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Supplier
from app.services.google_search_service import google_search
from app.services.llm_service import chat_completion

logger = structlog.get_logger(__name__)

SUPPLIER_TYPE_PRIORITY = {
    'manufacturer': 0,
    'distributor': 1,
    'wholesaler': 2,
    'retail': 3,
    'unknown': 4,
}

# Кэш анализа сайтов с ограничением размера (простой FIFO)
_website_analysis_cache: Dict[str, Dict[str, Any]] = {}
_MAX_CACHE_SIZE = 200

def _infer_type(title: str, snippet: str = '') -> str:
    text = f'{title} {snippet}'.lower()
    if any(w in text for w in ['производитель', 'завод', 'manufacturer', 'производство']):
        return 'manufacturer'
    if any(w in text for w in ['дистрибьютор', 'distributor', 'официальный дилер']):
        return 'distributor'
    if any(w in text for w in ['опт', 'wholesale', 'оптовый']):
        return 'wholesaler'
    if any(w in text for w in ['магазин', 'shop', 'retail', 'розница']):
        return 'retail'
    return 'unknown'

def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')
    except Exception:
        return url

def _normalize_supplier(
    id: Any,
    name: str,
    email: str,
    phone: str,
    website: str,
    source: str,
    match_relevance: str,
    is_new: bool,
    type: str = '',
    snippet: str = '',
) -> Dict[str, Any]:
    return {
        'id': id,
        'name': name,
        'email': email,
        'phone': phone,
        'website': website,
        'source': source,
        'match_relevance': match_relevance,
        'is_new': is_new,
        'type': type or _infer_type(name, snippet),
        'snippet': snippet[:200] if snippet else '',
    }

async def search_suppliers_in_db(db: AsyncSession, query: str, limit: int = 10) -> List[Supplier]:
    stmt = select(Supplier).where(
        Supplier.is_active == True,
        or_(
            Supplier.name.ilike(f'%{query}%'),
            Supplier.email.ilike(f'%{query}%'),
            Supplier.tags.cast(str).ilike(f'%{query}%'),
        ),
    ).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def search_suppliers_external(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    results = await google_search(query, num=limit)
    suppliers = []
    for item in results:
        link = item.get('link', '')
        title = item.get('title', '')
        snippet = item.get('snippet', '')
        suppliers.append(_normalize_supplier(
            id=None, name=title, email='', phone='', website=link,
            source='google', match_relevance='medium', is_new=True, snippet=snippet,
        ))
    return suppliers

async def analyze_website_with_llm(website: str, search_query: str) -> Dict[str, Any]:
    if not website:
        return {}
    domain = _extract_domain(website)
    if domain in _website_analysis_cache:
        return _website_analysis_cache[domain]
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(website)
            resp.raise_for_status()
            html = resp.text
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)[:3000]
    except Exception as e:
        logger.warning('supplier_search.website_fetch_failed', url=website, error=str(e))
        return {}
    prompt = f"""Проанализируй сайт компании на основе текста.
Текст сайта:
{text}
Определи:
1. type: manufacturer | distributor | wholesaler | retail | unknown
2. relevance_to_query: high | medium | low (насколько ассортимент соответствует запросу: {search_query})
3. email, phone, telegram, whatsapp (если видны)
4. legal_name (если видно)
5. inn (если указан)
Ответ — ТОЛЬКО JSON."""
    response = await chat_completion(prompt)
    if not response:
        return {}
    try:
        import json
        analysis = json.loads(response)
        # Простое ограничение кэша
        if len(_website_analysis_cache) >= _MAX_CACHE_SIZE:
            _website_analysis_cache.clear()
        _website_analysis_cache[domain] = analysis
        return analysis
    except Exception:
        return {}

async def search_suppliers_combined(db: AsyncSession, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    internal = await search_suppliers_in_db(db, query, limit)
    external = await search_suppliers_external(query, limit)
    seen_emails = set()
    seen_domains = set()
    result = []
    for s in internal:
        email = s.email or ''
        domain = _extract_domain(s.website) if s.website else ''
        if email and email in seen_emails:
            continue
        if domain and domain in seen_domains:
            continue
        if email:
            seen_emails.add(email)
        if domain:
            seen_domains.add(domain)
        result.append(_normalize_supplier(
            id=s.id, name=s.name, email=s.email, phone=s.phone, website=s.website,
            source='internal_db', match_relevance='high' if query.lower() in s.name.lower() else 'medium',
            is_new=False, type=s.type,
        ))

    MAX_WEBSITE_ANALYSIS = 5
    analyzed = 0
    for ext in external:
        email = ext.get('email', '')
        domain = _extract_domain(ext.get('website', ''))
        if email and email in seen_emails:
            continue
        if domain and domain in seen_domains:
            continue
        if email:
            seen_emails.add(email)
        if domain:
            seen_domains.add(domain)
        ext['id'] = None
        ext['is_new'] = True
        if analyzed < MAX_WEBSITE_ANALYSIS:
            analysis = await analyze_website_with_llm(ext.get('website', ''), query)
            if analysis:
                ext['type'] = analysis.get('type', ext.get('type', 'unknown'))
                ext['email'] = ext.get('email') or analysis.get('email', '')
                ext['phone'] = ext.get('phone') or analysis.get('phone', '')
                if analysis.get('inn'):
                    ext['inn'] = analysis['inn']
                if analysis.get('legal_name'):
                    ext['name'] = analysis['legal_name']
                ext['match_relevance'] = analysis.get('relevance_to_query', ext.get('match_relevance', 'medium'))
            analyzed += 1
        result.append(ext)

    priority_map = {'high': 0, 'medium': 1, 'low': 2}
    result.sort(key=lambda x: (SUPPLIER_TYPE_PRIORITY.get(x.get('type', 'unknown'), 4), priority_map.get(x.get('match_relevance', 'medium'), 1)))
    return result[:limit]
