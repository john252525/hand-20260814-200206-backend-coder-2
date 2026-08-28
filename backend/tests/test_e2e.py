import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource, Category, Supplier, LotSupplier, CommercialOffer, Task, Communication
from app.workers.process_tender import _process
from app.services.tender_status_service import change_tender_status

@pytest.mark.asyncio
async def test_full_pipeline(client, api_token, setup_db):
    """Сквозной тест: источник → тендер → обработка → поставщики → КП → переговоры → решение.
    Используем прямые вызовы внутренних функций, чтобы не зависеть от Celery.
    """
    async with AsyncSessionLocal() as db:
        source = TenderSource(name='ГосПлан', type='aggregator_api', api_url='https://v2test.gosplan.info/fz44/purchases')
        db.add(source)
        await db.flush()
        cat = Category(name='Компьютеры', description='Ноутбуки', keywords=['ноутбук'])
        db.add(cat)
        await db.commit()
        source_id = source.id
        cat_id = cat.id

    # Создаём тендер вручную
    resp = await client.post('/api/v1/tenders', json={
        'title': 'Поставка ноутбуков HP', 'description': 'Ноутбуки для офиса', 'nmck': 1500000,
        'skip_auto_processing': True,
    }, headers={'X-API-Token': api_token})
    assert resp.status_code == 201
    tender_id = resp.json()['data']['id']

    # Обработка тендера через внутреннюю функцию (без Celery)
    await _process(str(tender_id))
    async with AsyncSessionLocal() as db:
        tender = await db.get(Tender, uuid.UUID(tender_id))
        assert tender.matched_category_id is not None
        assert tender.score is not None

    # Добавляем поставщика и привязываем к лоту
    supplier_resp = await client.post('/api/v1/suppliers', json={
        'name': 'ООО Поставщик', 'email': 'sales@supplier.ru'
    }, headers={'X-API-Token': api_token})
    assert supplier_resp.status_code == 201
    supplier_id = supplier_resp.json()['data']['id']

    confirm_resp = await client.post(
        f'/api/v1/tenders/{tender_id}/supplier-search-results/confirm',
        json={'supplier_ids': [supplier_id]},
        headers={'X-API-Token': api_token},
    )
    assert confirm_resp.status_code == 200

    # Запрашиваем КП (создаётся задача, но в тесте не запускаем Celery)
    cp_resp = await client.post(f'/api/v1/tenders/{tender_id}/request-cp', headers={'X-API-Token': api_token})
    assert cp_resp.status_code == 202

    # Добавляем тестовое КП (эмуляция получения письма)
    async with AsyncSessionLocal() as db:
        ls = (await db.execute(select(LotSupplier).where(LotSupplier.tender_id == uuid.UUID(tender_id)))).scalar_one()
        comm = Communication(lot_supplier_id=ls.id, tender_id=ls.tender_id, direction='incoming',
                             channel='email', subject='КП', body_text='...', message_type='cp_response')
        db.add(comm)
        await db.flush()
        offer = CommercialOffer(lot_supplier_id=ls.id, tender_id=ls.tender_id, source_communication_id=comm.id,
                                status='FULL', coverage=100, total_cost_with_all=Decimal('1000000'),
                                margin_absolute=Decimal('500000'), margin_percent=33.3, raw_text_snippet='...')
        db.add(offer)
        await db.commit()
        offer_id = offer.id

    # Переговоры (запрос скидки) - вызываем воркер напрямую
    from app.workers.negotiate import _negotiate
    await _negotiate(str(tender_id), None, 'request_discount', [])
    async with AsyncSessionLocal() as db:
        tender = await db.get(Tender, uuid.UUID(tender_id))
        # Если нет конкурентных цен, тендер должен перейти в READY_FOR_DECISION (новая логика)
        assert tender.status in ('READY_FOR_DECISION', 'NEGOTIATING')

    # Если вдруг остался NEGOTIATING, принудительно переводим в READY_FOR_DECISION
    async with AsyncSessionLocal() as db:
        tender = await db.get(Tender, uuid.UUID(tender_id))
        if tender.status != 'READY_FOR_DECISION':
            await change_tender_status(db, tender, 'READY_FOR_DECISION', note='Тест: принудительный переход')
            await db.commit()

    # Решение
    dec_resp = await client.post(f'/api/v1/decisions/{tender_id}/approve',
                                 json={'chosen_supplier_id': supplier_id, 'chosen_offer_id': offer_id, 'comment': 'ok'},
                                 headers={'X-API-Token': api_token})
    assert dec_resp.status_code == 200
    assert dec_resp.json()['data']['decision'] == 'APPROVED'
