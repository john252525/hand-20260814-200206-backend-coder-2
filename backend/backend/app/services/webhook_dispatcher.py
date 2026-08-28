import hmac
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.models import Webhook


async def send_webhook_event(event: str, payload: dict, db: Optional[AsyncSession] = None) -> None:
    """Отправляет событие во все активные вебхуки. При неудаче ставит задачу на retry."""
    async def _send(webhook: Webhook, payload: dict):
        data = json.dumps({"event": event, **payload}).encode()
        signature = hmac.new(webhook.secret.encode(), data, hashlib.sha256).hexdigest()
        headers = {"X-Webhook-Signature": signature, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(webhook.url, content=data, headers=headers)
            if resp.status_code < 300:
                webhook.last_status = "success"
                webhook.retry_count = 0
            else:
                webhook.last_status = "error"
                webhook.retry_count += 1
                # Планируем retry через 1с, 2с, 4с
                from app.workers.celery_app import celery_app
                celery_app.send_task("webhook_retry", args=[str(webhook.id), event, payload], countdown=1)
        except Exception:
            webhook.last_status = "error"
            webhook.retry_count += 1
            from app.workers.celery_app import celery_app
            celery_app.send_task("webhook_retry", args=[str(webhook.id), event, payload], countdown=1)
        webhook.last_sent_at = datetime.now(timezone.utc)

    if db is None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(Webhook).where(Webhook.is_active == True))
            webhooks = result.scalars().all()
            for wh in webhooks:
                if event in wh.events:
                    await _send(wh, payload)
            await session.commit()
    else:
        result = await db.execute(select(Webhook).where(Webhook.is_active == True))
        webhooks = result.scalars().all()
        for wh in webhooks:
            if event in wh.events:
                await _send(wh, payload)
        await db.commit()
