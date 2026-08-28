from fastapi import APIRouter
from app.api.v1 import (
    tokens, settings, categories, tasks, tenders, suppliers,
    communications, commercial_offers, negotiations, decisions,
    webhooks, files, metrics, tender_sources, embeddings,
)

api_router = APIRouter()
api_router.include_router(metrics.router, tags=["metrics"])
api_router.include_router(tokens.router, prefix="/tokens", tags=["tokens"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(tenders.router, prefix="/tenders", tags=["tenders"])
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["suppliers"])
api_router.include_router(communications.router, prefix="/communications", tags=["communications"])
api_router.include_router(commercial_offers.router, prefix="/commercial-offers", tags=["commercial-offers"])
api_router.include_router(negotiations.router, prefix="/tenders", tags=["negotiations"])
api_router.include_router(decisions.router, prefix="/decisions", tags=["decisions"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(tender_sources.router, prefix="/tender-sources", tags=["tender-sources"])
api_router.include_router(embeddings.router, prefix="/embeddings", tags=["embeddings"])
