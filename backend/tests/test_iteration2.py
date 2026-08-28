import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource, TenderPosition, CommercialOffer, LotSupplier, Supplier, Communication, OfferPosition, CommunicationAttachment
from app.services.scoring_service import calculate_score, estimate_margin_percent
from app.services.cp_parser import save_parsed_cp
from app.workers.process_incoming import _process_incoming_email

@pytest.mark.asyncio
async def test_scoring_uses_historical_margin(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="sc-1", title="Ноутбуки", nmck=Decimal("1000000"))
        db.add(tender)
        await db.flush()
        pos = TenderPosition(tender_id=tender.id, position_number=1, name="Ноутбук HP", quantity=10, unit="шт")
        db.add(pos)
        await db.flush()
        source2 = TenderSource(name="Test2", type="aggregator_api", api_url="https://test2")
        db.add(source2)
        await db.flush()
        tender2 = Tender(source_id=source2.id, source_tender_id="sc-2", title="Другое", nmck=Decimal("100000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender2, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender2.id, supplier_id=supplier.id)
        db.add(ls)
        await db.flush()
        offer = CommercialOffer(lot_supplier_id=ls.id, tender_id=tender2.id, status="FULL")
        db.add(offer)
        await db.flush()
        db.add(OfferPosition(commercial_offer_id=offer.id, tender_position_id=None, supplier_name="Ноутбук HP ProBook", match_type="exact", price_per_unit=Decimal("50000")))
        await db.commit()
        est = await estimate_margin_percent(db, tender)
        assert est is not None
        assert est == pytest.approx(50.0)
        settings = {"margin_calculation_mode": "auto", "margin_fallback_score": 50}
        score, _ = await calculate_score(tender, settings, db=db)
        assert score > 50

@pytest.mark.asyncio
async def test_cp_parser_invalid_positions_marks_error(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="cp-1", title="Test", nmck=Decimal("1000"))
        db.add(tender)
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Pos", quantity=1, unit="шт"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id)
        db.add(ls)
        await db.flush()
        offer = CommercialOffer(lot_supplier_id=ls.id, tender_id=tender.id, status="PROCESSING")
        db.add(offer)
        await db.commit()
        await save_parsed_cp(db, offer, {"positions": []}, tender)
        assert offer.status == "ERROR"

@pytest.mark.asyncio
async def test_incoming_email_uses_attachments(setup_db, tmp_path):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="att-1", title="Ноутбуки", nmck=Decimal("1500000"))
        supplier = Supplier(name="ООО Поставщик", email="sales@supplier.ru")
        db.add_all([tender, supplier])
        await db.flush()
        db.add(TenderPosition(tender_id=tender.id, position_number=1, name="Ноутбук", quantity=10, unit="шт"))
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status="CP_REQUESTED")
        db.add(ls)
        await db.commit()
    attach_path = tmp_path / "cp.txt"
    attach_path.write_text("Коммерческое предложение: Ноутбук HP - 100000 руб за шт.", encoding="utf-8")
    with patch("app.workers.process_incoming.classify_email", new_callable=AsyncMock, return_value="cp_response"), \
         patch("app.workers.process_incoming.parse_cp_task.delay", return_value=AsyncMock(id="celery-id")):
        email_data = {
            "message_id": "msg-att",
            "from_": "sales@supplier.ru",
            "subject": "КП",
            "body": "Прошу рассмотреть",
            "attachments": [str(attach_path)],
        }
        await _process_incoming_email(email_data)
    async with AsyncSessionLocal() as db:
        offer = (await db.execute(select(CommercialOffer).where(CommercialOffer.tender_id == tender.id))).scalar_one()
        assert "Коммерческое предложение" in offer.raw_text_snippet
        att = (await db.execute(select(CommunicationAttachment).join(Communication).where(Communication.tender_id == tender.id))).scalars().first()
        assert att is not None
        assert att.filename == "cp.txt"

@pytest.mark.asyncio
async def test_negotiation_agent_llm_called(setup_db):
    from app.services.negotiation_service import generate_clarification_email
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="neg-1", title="Тендер", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id)
        db.add(ls)
        await db.flush()
        offer = CommercialOffer(lot_supplier_id=ls.id, tender_id=tender.id, clarification_items=["Не указана цена"], clarification_needed=True)
        db.add(offer)
        await db.commit()
    mock_response = '{"subject": "Уточнение", "body": "Уточните, пожалуйста"}'
    with patch("app.services.negotiation_service.chat_completion", new_callable=AsyncMock, return_value=mock_response):
        subject, body = await generate_clarification_email(db, ls, offer)
        assert subject == "Уточнение"
        assert body == "Уточните, пожалуйста"

@pytest.mark.asyncio
async def test_api_responses_have_new_fields(client, api_token, setup_db):
    from datetime import datetime, timezone
    async with AsyncSessionLocal() as db:
        source = TenderSource(name="Test", type="aggregator_api", api_url="https://test")
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id="api-1", title="Ноутбуки", nmck=Decimal("1000"))
        supplier = Supplier(name="Supplier", email="s@test.com")
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id)
        db.add(ls)
        await db.flush()
        comm = Communication(lot_supplier_id=ls.id, tender_id=tender.id, direction="incoming", channel="email", subject="КП", body_text="...", message_type="cp_response", received_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        db.add(comm)
        await db.flush()
        offer = CommercialOffer(lot_supplier_id=ls.id, tender_id=tender.id, source_communication_id=comm.id, status="FULL")
        db.add(offer)
        await db.commit()
        tender_id = tender.id
    resp = await client.get(f"/api/v1/tenders/{tender_id}", headers={"X-API-Token": api_token})
    assert resp.status_code == 200
    assert resp.json()["data"]["source"]["name"] == "Test"
    resp2 = await client.get("/api/v1/commercial-offers", headers={"X-API-Token": api_token})
    assert resp2.status_code == 200
    offer_data = resp2.json()["data"][0]
    assert offer_data["tender_title"] == "Ноутбуки"
    assert offer_data["supplier_name"] == "Supplier"
    assert offer_data["received_at"] is not None