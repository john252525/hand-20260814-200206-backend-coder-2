import hmac
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Webhook

router = APIRouter()


class WebhookCreate(BaseModel):
    url: str
    events: list[str]
    secret: str = ""
    is_active: bool = True


class WebhookUpdate(BaseModel):
    url: Optional[str] = None
    events: Optional[list[str]] = None
    secret: Optional[str] = None
    is_active: Optional[bool] = None


def _mask_secret(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "****"
    return secret[:4] + "..." + secret[-4:]


@router.get("")
async def list_webhooks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Webhook))
    webhooks = result.scalars().all()
    return {
        "success": True,
        "data": [
            {
                "id": w.id,
                "url": w.url,
                "events": w.events,
                "secret_preview": _mask_secret(w.secret),
                "is_active": w.is_active,
                "last_sent_at": w.last_sent_at,
                "last_status": w.last_status,
                "retry_count": w.retry_count,
                "created_at": w.created_at,
            }
            for w in webhooks
        ],
    }


@router.post("", status_code=201)
async def create_webhook(payload: WebhookCreate, db: AsyncSession = Depends(get_db)):
    wh = Webhook(**payload.model_dump())
    db.add(wh)
    await db.commit()
    await db.refresh(wh)
    return {"success": True, "data": {"id": wh.id, "url": wh.url}}


@router.get("/{webhook_id}")
async def get_webhook(webhook_id: UUID, db: AsyncSession = Depends(get_db)):
    wh = await db.get(Webhook, webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Webhook not found"})
    return {
        "success": True,
        "data": {
            "id": wh.id,
            "url": wh.url,
            "events": wh.events,
            "secret_preview": _mask_secret(wh.secret),
            "is_active": wh.is_active,
            "last_sent_at": wh.last_sent_at,
            "last_status": wh.last_status,
            "retry_count": wh.retry_count,
            "created_at": wh.created_at,
        },
    }


@router.patch("/{webhook_id}")
async def update_webhook(webhook_id: UUID, payload: WebhookUpdate, db: AsyncSession = Depends(get_db)):
    wh = await db.get(Webhook, webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Webhook not found"})
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(wh, field, value)
    await db.commit()
    await db.refresh(wh)
    return {"success": True, "data": {"id": wh.id}}


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: UUID, db: AsyncSession = Depends(get_db)):
    wh = await db.get(Webhook, webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Webhook not found"})
    await db.delete(wh)
    await db.commit()
    return {"success": True, "data": None}


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: UUID, db: AsyncSession = Depends(get_db)):
    wh = await db.get(Webhook, webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Webhook not found"})

    payload = json.dumps({"event": "test", "message": "Test webhook"}).encode()
    signature = hmac.new(wh.secret.encode(), payload, hashlib.sha256).hexdigest()
    headers = {"X-Webhook-Signature": signature, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(wh.url, content=payload, headers=headers)
        if resp.status_code < 300:
            wh.last_status = "success"
            wh.retry_count = 0
        else:
            wh.last_status = "error"
            wh.retry_count += 1
    except Exception:
        wh.last_status = "error"
        wh.retry_count += 1
    wh.last_sent_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "success": True,
        "data": {
            "webhook_url": wh.url,
            "signature": signature,
            "last_status": wh.last_status,
        },
    }
