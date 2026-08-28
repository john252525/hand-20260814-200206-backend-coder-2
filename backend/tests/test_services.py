import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Category, Tender, TenderSource
from app.services.scoring_service import calculate_score
from app.services.tender_status_service import change_tender_status


@pytest.mark.asyncio
async def test_status_service(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Test", nmck=Decimal("1000"))
        db.add(tender)
        await db.flush()
        await change_tender_status(db, tender, "SCORING", note="test")
        await db.commit()
        assert tender.status == "SCORING"
        result = await db.execute(select(TenderStatusHistory).where(TenderStatusHistory.tender_id == tender.id))
        history = result.scalars().all()
        assert len(history) == 1


@pytest.mark.asyncio
async def test_scoring(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(
            source_id=source.id,
            source_tender_id="123",
            title="Test",
            nmck=Decimal("1000000"),
            deadline_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(tender)
        await db.flush()
        settings = {
            "weight_margin": 40, "weight_simplicity": 30, "weight_volume": 20, "weight_competition": 10,
            "margin_fallback_score": 50, "default_competition_score": 50,
            "volume_thresholds": {"low": 100000, "medium": 1000000, "high": 5000000},
            "volume_scores": {"low": 20, "medium": 50, "high": 80, "very_high": 95},
        }
        score, components = calculate_score(tender, settings)
        assert 0 <= score <= 100
        assert "margin_score" in components
