from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

celery_app = Celery(
    "tender_pipeline",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.sync_tenders",
        "app.workers.process_tender",
        "app.workers.search_suppliers",
        "app.workers.send_communications",
        "app.workers.parse_cp",
        "app.workers.process_incoming",
        "app.workers.webhook_retry",
    ],
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
    beat_schedule={
        "sync-tenders-periodic": {
            "task": "sync_tenders",
            "schedule": crontab(minute="*/30"),  # каждые 30 минут
        },
        "check-imap-periodic": {
            "task": "check_incoming_emails",
            "schedule": crontab(minute="*/5"),  # каждые 5 минут
        },
    },
)

celery_app.autodiscover_tasks(["app.workers"])
