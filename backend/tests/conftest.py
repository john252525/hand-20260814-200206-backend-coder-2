import asyncio
import os
import sys
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

sys.path.append(str(Path(__file__).parent.parent))
os.environ["APP_ENV"] = "test"
os.environ["POSTGRES_DB"] = "tender_pipeline_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"

from app.main import app  # noqa: E402
from app.core.database import Base, engine, AsyncSessionLocal  # noqa: E402

DEFAULT_SETTINGS_TEST = {
    'company': {
        'legal_name': '', 'inn': '', 'kpp': '', 'ogrn': '', 'legal_address': '',
        'contact_person': '', 'contact_email': '', 'contact_phone': '', 'email_signature': '',
        'has_license': False, 'has_sro': False,
    },
    'scoring': {
        'min_total_score': 60, 'min_margin_percent': 15.0, 'max_risk_level': 'MEDIUM',
        'weight_margin': 40, 'weight_simplicity': 30, 'weight_volume': 20, 'weight_competition': 10,
        'volume_thresholds': {'low': 100000, 'medium': 1000000, 'high': 5000000},
        'volume_scores': {'low': 20, 'medium': 50, 'high': 80, 'very_high': 95},
        'default_competition_score': 50, 'margin_calculation_mode': 'auto', 'margin_fallback_score': 50,
    },
    'templates': {
        'cp_request': {
            'subject': 'Запрос КП: {lot_name}',
            'body': 'Тело письма {positions_table} {company_signature}'
        }
    }
}

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def setup_db():
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        await db.execute(text("TRUNCATE idempotency_keys RESTART IDENTITY"))
        await db.execute(text("TRUNCATE api_tokens RESTART IDENTITY"))
        await db.execute(text("TRUNCATE settings RESTART IDENTITY"))
        await db.commit()
    from app.models import Setting
    async with AsyncSessionLocal() as db:
        for section, values in DEFAULT_SETTINGS_TEST.items():
            for key, value in values.items():
                db.add(Setting(section=section, key=key, value=value, description=""))
        await db.commit()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def client(setup_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def api_token(setup_db):
    from app.models import ApiToken
    import uuid
    async with AsyncSessionLocal() as db:
        token = ApiToken(token=uuid.uuid4().hex, description="test")
        db.add(token)
        await db.commit()
        await db.refresh(token)
        return token.token
