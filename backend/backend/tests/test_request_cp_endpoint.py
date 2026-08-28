import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import Communication, LotSupplier, Supplier, Tender, TenderSource


@pytest.mark.asyncio
async def test_request_cp_endpoint(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки HP", nmck=Decimal("1500000"))
        supplier = Supplier(name="ООО Компьютерный мир", email="sales@compworld.ru")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="PENDING")
        db.add(ls)
        await db.commit()
        tender_id = tender.id

    # Вызываем эндпоинт без supplier_ids (рассылка всем)
    resp = await client.post(
        f"/api/v1/tenders/{tender_id}/request-cp",
        json={},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 202
    task_id = resp.json()["data"]["task_id"]
    assert task_id is not None

    # Проверяем, что задача создана
    async with AsyncSessionLocal() as db:
        from app.models import Task
        task = await db.get(Task, uuid.UUID(task_id))
        assert task is not None
        assert task.task_type == "SEND_CP"
