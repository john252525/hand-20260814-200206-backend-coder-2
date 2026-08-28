from typing import List, Dict, Any
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Supplier
from app.services.google_search_service import google_search

SUPPLIER_TYPE_PRIORITY = {
    "manufacturer": 0,
    "distributor": 1,
    "wholesaler": 2,
    "retail": 3,
    "unknown": 4,
}

def _infer_type(title: str, snippet: str = "") -> str:
    text = f"{title} {snippet}".lower()
    if any(w in text for w in ["производитель", "завод", "manufacturer", "производство"]):
        return "manufacturer"
    if any(w in text for w in ["дистрибьютор", "distributor", "официальный дилер"]):
        return "distributor"
    if any(w in text for w in ["опт", "wholesale", "оптовый"]):
        return "wholesaler"
    if any(w in text for w in ["магазин", "shop", "retail", "розница"]):
        return "retail"
    return "unknown"

def _normalize_supplier(
    id: Any,
    name: str,
    email: str,
    phone: str,
    website: str,
    source: str,
    match_relevance: str,
    is_new: bool,
    type: str = "",
    snippet: str = "",
) -> Dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "email": email,
        "phone": phone,
        "website": website,
        "source": source,
        "match_relevance": match_relevance,
        "is_new": is_new,
        "type": type or _infer_type(name, snippet),
        "snippet": snippet[:200] if snippet else "",
    }

async def search_suppliers_in_db(
    db: AsyncSession,
    query: str,
    limit: int = 10,
) -> List[Supplier]:
    stmt = select(Supplier).where(
        Supplier.is_active == True,
        or_(
            Supplier.name.ilike(f"%{query}%"),
            Supplier.email.ilike(f"%{query}%"),
            Supplier.tags.cast(str).ilike(f"%{query}%"),
        ),
    ).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def search_suppliers_external(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    results = await google_search(query, num=limit)
    suppliers = []
    for item in results:
        link = item.get("link", "")
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        suppliers.append(
            _normalize_supplier(
                id=None,
                name=title,
                email="",
                phone="",
                website=link,
                source="google",
                match_relevance="medium",
                is_new=True,
                snippet=snippet,
            )
        )
    return suppliers

async def search_suppliers_combined(
    db: AsyncSession,
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    internal = await search_suppliers_in_db(db, query, limit)
    external = await search_suppliers_external(query, limit)
    seen_emails = set()
    seen_domains = set()
    result = []
    for s in internal:
        email = s.email or ""
        domain = s.website.replace("https://", "").replace("http://", "").split("/")[0] if s.website else ""
        if email and email in seen_emails:
            continue
        if domain and domain in seen_domains:
            continue
        if email:
            seen_emails.add(email)
        if domain:
            seen_domains.add(domain)
        result.append(
            _normalize_supplier(
                id=s.id,
                name=s.name,
                email=s.email,
                phone=s.phone,
                website=s.website,
                source="internal_db",
                match_relevance="high" if query.lower() in s.name.lower() else "medium",
                is_new=False,
                type=s.type,
            )
        )
    for ext in external:
        email = ext.get("email", "")
        domain = ext.get("website", "").replace("https://", "").replace("http://", "").split("/")[0] if ext.get("website") else ""
        if email and email in seen_emails:
            continue
        if domain and domain in seen_domains:
            continue
        if email:
            seen_emails.add(email)
        if domain:
            seen_domains.add(domain)
        ext["id"] = None
        ext["is_new"] = True
        # Тип уже определён в _normalize_supplier
        result.append(ext)
    priority_map = {"high": 0, "medium": 1, "low": 2}
    result.sort(key=lambda x: (SUPPLIER_TYPE_PRIORITY.get(x.get("type", "unknown"), 4), priority_map.get(x.get("match_relevance", "medium"), 1)))
    return result[:limit]