import asyncio
import structlog
from datetime import datetime, timedelta, timezone
from uuid import UUID
import httpx
from sqlalchemy import select
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import Tender, TenderSource, Task, TenderStatusHistory
from app.workers.celery_app import celery_app

logger = structlog.get_logger(__name__)

GOSPLAN_TEST_URL = 'https://v2test.gosplan.info/fz44/purchases'
MAX_SKIP = 1000
BASE_SINCE = '2024-01-01T00:00:00Z'

@celery_app.task(name='sync_tenders', bind=True)
def sync_tenders(
    self,
    source_id: str | None = None,
    task_id: str | None = None,
    since: str | None = None,
    full_resync: bool = False,
) -> dict:
    """
    Синхронизация тендеров из источника.

    :param source_id: UUID источника
    :param task_id: UUID задачи (опционально)
    :param since: дата, начиная с которой запрашивать (если None, определяется автоматически)
    :param full_resync: если True, игнорируется last_sync_at и сбрасываются missing_count
    """
    try:
        asyncio.run(_sync(source_id, task_id, since, full_resync))
        return {'status': 'completed'}
    except Exception as e:
        logger.error('sync_tenders.failed', error=str(e))
        if task_id:
            asyncio.run(_update_task_error(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)

async def _update_task_error(task_id: str, error: str):
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        if task:
            task.status = 'FAILED'
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

async def _sync(
    source_id: str | None = None,
    task_id: str | None = None,
    since: str | None = None,
    full_resync: bool = False,
):
    if task_id:
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = 'IN_PROGRESS'
                await db.commit()

    async with AsyncSessionLocal() as db:
        if source_id:
            result = await db.execute(select(TenderSource).where(TenderSource.id == UUID(source_id)))
            source = result.scalar_one_or_none()
        else:
            result = await db.execute(select(TenderSource).where(TenderSource.is_active == True))
            source = result.scalars().first()
        if not source:
            logger.warning('sync_tenders.source_not_found', source_id=source_id)
            return

        url = source.api_url or settings.tender_source_api_url or GOSPLAN_TEST_URL
        api_key = source.api_key_encrypted or ''

        # Определяем начальную дату
        if full_resync:
            next_since = BASE_SINCE
            # Сбрасываем missing_count для всех тендеров источника
            all_tenders = (await db.execute(select(Tender).where(Tender.source_id == source.id))).scalars().all()
            for t in all_tenders:
                t.missing_count = 0
            await db.flush()
        elif since:
            next_since = since
        elif source.last_sync_at:
            last_sync = source.last_sync_at
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=timezone.utc)
            since_dt = last_sync - timedelta(hours=1)
            next_since = since_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            next_since = BASE_SINCE

        # Получаем page_size и приводим к int
        raw_page_size = source.config.get('page_size', 50) if source.config else 50
        try:
            page_size = int(raw_page_size)
        except (TypeError, ValueError):
            logger.warning('sync_tenders.invalid_page_size', value=raw_page_size, source_id=str(source.id))
            page_size = 50
        page_size = max(1, min(page_size, 100))

        skip = 0
        created, updated, found_ids = 0, 0, set()
        full_sync_completed = False
        max_loops = 200
        loops = 0
        prev_cursor_published = None

        headers = {}
        if api_key:
            headers['X-API-Key'] = api_key

        while loops < max_loops:
            loops += 1
            params = {
                'limit': page_size,
                'skip': skip,
                'published_after': next_since,
                'sort': 'published_at_desc',
            }
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(url, params=params, headers=headers)
                    resp.raise_for_status()
                    items = resp.json()
            except Exception as e:
                source.last_sync_status = 'error'
                source.last_error = str(e)
                await db.commit()
                if task_id:
                    await _update_task_error(task_id, str(e))
                return

            if not items:
                full_sync_completed = True
                break

            for item in items:
                purchase_number = item.get('purchase_number', '')
                if not purchase_number:
                    continue
                found_ids.add(purchase_number)
                existing = (await db.execute(
                    select(Tender).where(
                        Tender.source_id == source.id,
                        Tender.source_tender_id == purchase_number
                    )
                )).scalar_one_or_none()

                if existing:
                    if existing.status == 'ARCHIVED':
                        # Восстанавливаем тендер и пишем в историю
                        db.add(TenderStatusHistory(
                            tender_id=existing.id,
                            status='NEW',
                            previous_status='ARCHIVED',
                            note='Восстановлен после повторного появления в источнике',
                        ))
                        existing.status = 'NEW'
                        existing.missing_count = 0
                        logger.info(
                            'sync_tenders.tender_restored',
                            tender_id=str(existing.id),
                            source_tender_id=purchase_number,
                        )
                    existing.title = item.get('object_info', existing.title)
                    existing.description = item.get('object_info', existing.description)
                    existing.nmck = item.get('max_price')
                    existing.deadline_at = item.get('collecting_finished_at') or item.get('submission_close_at') or existing.deadline_at
                    customers = item.get('customers') or []
                    if customers:
                        existing.customer_inn = str(customers[0])
                    existing.missing_count = 0
                    updated += 1
                    continue

                customers = item.get('customers') or []
                customer_inn = str(customers[0]) if customers else ''
                tender = Tender(
                    source_id=source.id,
                    source_tender_id=purchase_number,
                    title=item.get('object_info', 'Без названия'),
                    description=item.get('object_info', ''),
                    nmck=item.get('max_price'),
                    currency=item.get('currency_code', 'RUB'),
                    published_at=item.get('published_at'),
                    deadline_at=item.get('collecting_finished_at') or item.get('submission_close_at'),
                    customer_name=customer_inn,
                    customer_inn=customer_inn,
                    platform='ГосПлан',
                    source_url=f'{url}/{purchase_number}',
                    status='NEW',
                    missing_count=0,
                )
                db.add(tender)
                created += 1

            await db.flush()

            if len(items) < page_size:
                full_sync_completed = True
                break

            if skip + page_size >= MAX_SKIP:
                last_published = items[-1].get('published_at')
                if not last_published:
                    logger.warning('sync_tenders.max_skip_no_cursor', source_id=str(source.id))
                    break
                if last_published == prev_cursor_published:
                    logger.error('sync_tenders.cursor_not_advancing', source_id=str(source.id),
                                 published_at=last_published)
                    break
                prev_cursor_published = last_published
                next_since = last_published
                skip = 0
            else:
                skip += page_size

        if full_sync_completed:
            all_source_tenders = (await db.execute(
                select(Tender).where(Tender.source_id == source.id)
            )).scalars().all()
            for t in all_source_tenders:
                if t.source_tender_id in found_ids:
                    continue
                t.missing_count = (t.missing_count or 0) + 1
                if t.missing_count >= 2 and t.status not in ('APPROVED', 'REJECTED', 'ARCHIVED'):
                    db.add(TenderStatusHistory(
                        tender_id=t.id, status='ARCHIVED', previous_status=t.status,
                        note='Тендер отсутствовал в выдаче источника 2 раза подряд',
                    ))
                    t.status = 'ARCHIVED'

        source.last_sync_at = datetime.now(timezone.utc)
        source.last_sync_status = 'success' if full_sync_completed else 'partial'
        source.last_error = None if full_sync_completed else 'Синхронизация не завершена полностью (прервана)'
        await db.commit()

        if task_id:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = 'COMPLETED' if full_sync_completed else 'FAILED'
                if not full_sync_completed:
                    task.error_message = source.last_error
                task.output_data = {
                    'created': created,
                    'updated': updated,
                    'full_sync_completed': full_sync_completed,
                }
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()