import asyncio
from app.core.database import AsyncSessionLocal
from app.models import Task
from app.services.imap_service import fetch_unseen_emails
from app.workers.celery_app import celery_app
from app.workers.process_incoming import _process_incoming_email

@celery_app.task(name="check_incoming_emails", bind=True)
def check_incoming_emails(self) -> dict:
    try:
        asyncio.run(_check())
        return {"status": "completed"}
    except Exception as e:
        raise self.retry(exc=e, countdown=60)

async def _check():
    emails = await fetch_unseen_emails()
    for email_data in emails:
        await _process_incoming_email(email_data)
