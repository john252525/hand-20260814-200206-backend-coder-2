import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource


@pytest.mark.asyncio
async def test_create_tender_manual(client, api_token, setup_db):
    payload = {
        'title': 'Ручной тендер',
        'nmck': 1000000,
        'published_at': '2026-08-01T00:00:00Z',
        'deadline_at': '2026-09-01T00:00:00Z',
        'skip_auto_processing': True,
    }
    response = await client.post('/api/v1/tenders', json=payload, headers={'X-API-Token': api_token})
    assert response.status_code == 201
    data = response.json()['data']
    assert data['id']
    assert data['status'] == 'NEW'

    async with AsyncSessionLocal() as db:
        tender = await db.get(Tender, uuid.UUID(data['id']), options=[selectinload(Tender.source)])
        assert tender.source_tender_id is not None
        assert tender.source is not None
        assert tender.source.type == 'manual'


@pytest.mark.asyncio
async def test_create_tender_with_explicit_source(client, api_token, setup_db):
    async with AsyncSessionLocal() as db:
        source = TenderSource(name='Src', type='aggregator_api', api_url='https://example.com')
        db.add(source)
        await db.commit()
        source_id = source.id
    payload = {
        'source_id': str(source_id),
        'source_tender_id': 'ext-1',
        'title': 'Тендер из источника',
        'skip_auto_processing': True,
    }
    response = await client.post('/api/v1/tenders', json=payload, headers={'X-API-Token': api_token})
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_settings_history_route(client, api_token, setup_db):
    response = await client.get('/api/v1/settings/history', headers={'X-API-Token': api_token})
    assert response.status_code == 200
    assert response.json()['success'] is True
