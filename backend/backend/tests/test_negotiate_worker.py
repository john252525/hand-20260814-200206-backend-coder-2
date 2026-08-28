import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import (
    CommercialOffer, Communication, LotSupplier, Supplier, Tender, TenderPosition, TenderSource,
)
from app.workers.negotiate import _negotiate, _count_communications_by_type, _count_negotiation_communications_by_tender


@pytest.mark.asyncio
async def test_negotiate_worker_clarification_limit(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name='Test', type='aggregator_api', api_url='https://test')
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id='123', title='Ноутбуки', nmck=Decimal('1500000'))
        supplier = Supplier(name='Supplier', email='s@test.com')
        db.add_all([tender, supplier])
        await db.flush()
        ls = LotSupplier(tender_id=tender.id, supplier_id=supplier.id, status='RESPONDED')
        db.add(ls)
        await db.flush()
        ls_id = ls.id
        offer = CommercialOffer(
            lot_supplier_id=ls_id,
            tender_id=tender.id,
            status='PARTIAL',
            coverage=50.0,
            clarification_needed=True,
            clarification_items=['Не указана цена'],
            raw_text_snippet='...',
        )
        db.add(offer)
        # Уже отправлено 2 уточнения (лимит 2)
        for i in range(2):
            db.add(Communication(
                lot_supplier_id=ls_id,
                tender_id=tender.id,
                direction='outgoing',
                channel='email',
                subject='Уточнение',
                body_text='...',
                message_type='clarification',
                sent_at=datetime.now(timezone.utc),
            ))
        await db.commit()
        tender_id = tender.id

    await _negotiate(str(tender_id), None, 'request_clarification', [], None)

    async with AsyncSessionLocal() as db:
        comm_count = await _count_communications_by_type(db, tender_id, 'clarification')
        # Проверяем, что новых писем не добавилось
        ls = (await db.execute(select(LotSupplier).where(LotSupplier.tender_id == tender_id))).scalar_one()
        new_comms = (await db.execute(
            select(Communication).where(Communication.lot_supplier_id == ls.id, Communication.message_type == 'clarification')
        )).scalars().all()
        assert len(new_comms) == 2  # больше не добавилось
        assert ls.status == 'NO_RESPONSE'  # лимит исчерпан


@pytest.mark.asyncio
async def test_negotiate_worker_discount(setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name='Test', type='aggregator_api', api_url='https://test')
        db.add(source)
        await db.flush()
        tender = Tender(source_id=source.id, source_tender_id='456', title='Ноутбуки', nmck=Decimal('1500000'))
        supplier1 = Supplier(name='Supplier1', email='s1@test.com')
        supplier2 = Supplier(name='Supplier2', email='s2@test.com')
        db.add_all([tender, supplier1, supplier2])
        await db.flush()
        ls1 = LotSupplier(tender_id=tender.id, supplier_id=supplier1.id, status='RESPONDED')
        ls2 = LotSupplier(tender_id=tender.id, supplier_id=supplier2.id, status='RESPONDED')
        db.add_all([ls1, ls2])
        await db.flush()
        # У первого цена выше, у второго ниже -> будет скидка
        db.add(CommercialOffer(
            lot_supplier_id=ls1.id,
            tender_id=tender.id,
            status='FULL',
            coverage=100,
            clarification_needed=False,
            raw_text_snippet='...',
        ))
        await db.flush()
        # Добавить позиции для сравнения - упрощённо, используем просто competitive
        from app.models import OfferPosition, TenderPosition
        tp = TenderPosition(tender_id=tender.id, position_number=1, name='Ноутбук', quantity=1, unit='шт')
        db.add(tp)
        await db.flush()
        db.add(OfferPosition(commercial_offer_id=ls1.commercial_offers[0].id, tender_position_id=tp.id, supplier_name='Ноутбук', match_type='exact', price_per_unit=Decimal('100000'), total_price=Decimal('100000')))
        await db.flush()
        offer2 = CommercialOffer(
            lot_supplier_id=ls2.id,
            tender_id=tender.id,
            status='FULL',
            coverage=100,
            clarification_needed=False,
            raw_text_snippet='...',
        )
        db.add(offer2)
        await db.flush()
        db.add(OfferPosition(commercial_offer_id=offer2.id, tender_position_id=tp.id, supplier_name='Ноутбук', match_type='exact', price_per_unit=Decimal('90000'), total_price=Decimal('90000')))
        await db.commit()
        tender_id = tender.id

    await _negotiate(str(tender_id), None, 'request_discount', [], None)

    async with AsyncSessionLocal() as db:
        discount_comms = (await db.execute(
            select(Communication).where(Communication.tender_id == tender_id, Communication.message_type == 'discount_request')
        )).scalars().all()
        # Должно быть отправлено хотя бы одно письмо о скидке
        assert len(discount_comms) >= 1
        # Тендер переведён в NEGOTIATING
        tender = await db.get(Tender, tender_id)
        assert tender.status == 'NEGOTIATING'
        # cycles_completed корректно считается по тендеру
        cycles = await _count_negotiation_communications_by_tender(db, tender_id)
        assert cycles >= 1
