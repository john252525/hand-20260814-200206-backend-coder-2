import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import (
    CommercialOffer,
    Communication,
    LotSupplier,
    Supplier,
    Tender,
    TenderPosition,
    TenderSource,
)
from app.services.cp_parser import parse_cp_text, save_parsed_cp


@pytest.mark.asyncio
async def test_parse_cp_with_prices(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="123", title="Ноутбуки", nmck=Decimal("1500000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Ноутбук", quantity=10, unit="шт"))
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="CP_REQUESTED")
        db.add(ls)
        await db.flush()
        comm = Communication(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            direction="incoming",
            channel="email",
            subject="КП",
            body_text="Тест КП",
            message_type="cp_response",
        )
        db.add(comm)
        await db.flush()
        offer = CommercialOffer(
            lot_supplier_id=ls.id,
            tender_id=tender.id,
            source_communication_id=comm.id,
            raw_text_snippet="Тест КП",
        )
        db.add(offer)
        await db.commit()

        # Вручную задаём распарсенные данные с ценами
        parsed = {
            "positions": [
                {
                    "tender_position_number": 1,
                    "supplier_name": "Ноутбук HP",
                    "match_type": "exact",
                    "price_per_unit": 100000,
                    "quantity_available": 10,
                    "delivery_days": 14,
                    "nds_included": True,
                    "nds_rate": 20,
                    "notes": "",
                }
            ],
            "delivery_terms": {"delivery_days": 14, "delivery_cost": 5000},
            "payment_terms": {"prepayment_percent": 30},
            "valid_until": None,
        }

        await save_parsed_cp(db, offer, parsed, tender)
        await db.commit()

        assert offer.status == "FULL"
        assert offer.coverage == 100
        assert offer.total_cost == Decimal("1000000")
        assert offer.margin_percent is not None
