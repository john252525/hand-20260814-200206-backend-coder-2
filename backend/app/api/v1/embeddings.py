from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models import Tender
from app.services.embedding_service import generate_embedding, cosine_similarity

router = APIRouter()


class EmbeddingRequest(BaseModel):
    text: str


class SimilarityRequest(BaseModel):
    text1: str
    text2: str


class SearchSimilarRequest(BaseModel):
    text: str
    entity_type: str = "tender"
    top_k: int = 10
    min_similarity: float = 0.6
    filters: dict = {}


@router.post("/generate")
async def generate(payload: EmbeddingRequest, db: AsyncSession = Depends(get_db)):
    emb, degraded = await generate_embedding(payload.text)
    return {
        "success": True,
        "data": {
            "dimensions": len(emb),
            "tokens_used": 0,
            "embedding_preview": emb[:10],
            "is_degraded": degraded,
        },
    }


@router.post("/similarity")
async def similarity(payload: SimilarityRequest, db: AsyncSession = Depends(get_db)):
    emb1, _ = await generate_embedding(payload.text1)
    emb2, _ = await generate_embedding(payload.text2)
    sim = cosine_similarity(emb1, emb2)
    return {
        "success": True,
        "data": {
            "cosine_similarity": sim,
            "model": "text-embedding-3-small",
        },
    }


@router.post("/search-similar")
async def search_similar(payload: SearchSimilarRequest, db: AsyncSession = Depends(get_db)):
    if payload.entity_type not in ("tender", "category", "supplier"):
        raise HTTPException(status_code=400, detail={"code": "BAD_REQUEST", "message": "entity_type must be tender, category or supplier"})
    emb, _ = await generate_embedding(payload.text)
    query = select(Tender)
    if payload.filters.get("status"):
        query = query.where(Tender.status == payload.filters["status"])
    if payload.filters.get("category_id"):
        query = query.where(Tender.matched_category_id == UUID(payload.filters["category_id"]))
    result = await db.execute(query.limit(payload.top_k * 3))
    tenders = result.scalars().all()
    matches = []
    for t in tenders:
        if not t.embedding:
            continue
        sim = cosine_similarity(emb, t.embedding)
        if sim >= payload.min_similarity:
            matches.append({
                "id": t.id,
                "entity_type": "tender",
                "title": t.title,
                "similarity": sim,
                "nmck": t.nmck,
                "status": t.status,
            })
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return {"success": True, "data": matches[:payload.top_k]}
