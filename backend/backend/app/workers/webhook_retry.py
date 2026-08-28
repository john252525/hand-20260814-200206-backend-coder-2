import asyncio
import hmac
import hashlib
import json
from uuid import UUID
import httpx
from app.core.database import AsyncSessionLocal
from app.models import Webhook
from app.workers.celery_app import celery_app

@celery_app.task(name="webhook_retry", bind=True, max_retries=3, default_retry_delay=2)
def webhook_retry(self, webhook_id: str, event: str, payload: dict):
    """Повторная отправка вебхука с экспоненциальным backoff."""
    async def _retry():
        async with AsyncSessionLocal() as db:
            wh = await db.get(Webhook, UUID(webhook_id))
            if not wh or not wh.is_active:
                return
            data = json.dumps({"event": event, **payload}).encode()
            signature = hmac.new(wh.secret.encode(), data, hashlib.sha256).hexdigest()
            headers = {"X-Webhook-Signature": signature, "Content-Type": "application/json"}
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(wh.url, content=data, headers=headers)
                if resp.status_code < 300:
                    wh.last_status = "success"
                    wh.retry_count = 0
                else:
                    wh.last_status = "error"
                    wh.retry_count += 1
                    raise Exception(f"HTTP {resp.status_code}")
            except Exception:
                wh.last_status = "error"
                wh.retry_count += 1
                raise self.retry(exc=Exception("retry"), countdown=2 ** self.request.retries)
            wh.last_sent_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
            await db.commit()
    asyncio.run(_retry())
