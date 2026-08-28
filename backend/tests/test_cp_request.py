import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models import Communication, LotSupplier, Supplier, Tender, TenderSource, TenderPosition
from app.services.communication_service import generate_cp_request_email, send_cp_request_to_supplier


@pytest.mark.asyncio
async def test_generate_cp_request_email(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки HP", nmck=Decimal("1500000"))
        db.add(tender)
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Ноутбук", quantity=10, unit="шт"))
        await db.commit()

        subject, body = await generate_cp_request_email(tender, db)
        assert "Ноутбуки HP" in subject
        assert "Ноутбук" in body
        assert "{lot_name}" not in body


@pytest.mark.asyncio
async def test_send_cp_request_creates_communication(setup_db):
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

        # Принудительно загружаем позиции, чтобы избежать MissingGreenlet
        tender = await db.get(Tender, tender.id, options=[selectinload(Tender.positions)])
        comm = await send_cp_request_to_supplier(db, tender, supplier, ls)
        assert comm.id is not None
        assert comm.direction == "outgoing"
        assert comm.message_type == "cp_request"
        assert ls.status == "CP_REQUESTED"

        result = await db.execute(select(Communication).where(Communication.id == comm.id))
        assert result.scalar_one_or_none() is not None
