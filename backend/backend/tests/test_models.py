import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource, Supplier, Task


@pytest.mark.asyncio
async def test_create_tender(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(
            source_id=source.id,
            source_tender_id="123",
            title="Test tender",
            nmck=Decimal("1000.00"),
        )
        db.add(tender)
        await db.commit()
        assert tender.id is not None
        assert tender.created_at is not None
        assert tender.updated_at is not None


@pytest.mark.asyncio
async def test_create_supplier(setup_db):
    async with AsyncSessionLocal() as db:
        supplier = Supplier(name="Test Supplier", email="test@test.com")
        db.add(supplier)
        await db.commit()
        assert supplier.id is not None
        assert supplier.created_at is not None
        assert supplier.updated_at is not None


@pytest.mark.asyncio
async def test_create_task(setup_db):
    async with AsyncSessionLocal() as db:
        task = Task(task_type="TEST", status="PENDING")
        db.add(task)
        await db.commit()
        assert task.id is not None
        assert task.created_at is not None
        assert task.updated_at is not None
