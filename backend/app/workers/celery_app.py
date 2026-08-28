from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "tender_pipeline",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.sync_tenders", "app.workers.process_tender", "app.workers.search_suppliers", "app.workers.send_communications", "app.workers.parse_cp"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    task_soft_time_limit=3000,
    broker_connection_retry_on_startup=True,
)

celery_app.autodiscover_tasks(["app.workers"])
