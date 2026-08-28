import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import ApiToken, IdempotencyKey

# In-memory fallback для rate limit (если Redis недоступен)
_rate_store = {}


def _update_rate_in_memory(token_id: str, limit: int) -> bool:
    now = datetime.now(timezone.utc)
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    key = f"{token_id}:{minute_key}"
    current = _rate_store.get(key, 0)
    if current >= limit:
        return False
    _rate_store[key] = current + 1
    if len(_rate_store) > 10000:
        for k in list(_rate_store.keys()):
            if not k.endswith(minute_key):
                _rate_store.pop(k, None)
    return True


async def _is_rate_limited(token_id: str, limit: int) -> bool:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        now = datetime.now(timezone.utc)
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        key = f"rate:{token_id}:{minute_key}"
        current = await r.incr(key)
        if current == 1:
            await r.expire(key, 60)
        await r.aclose()
        return current > limit
    except Exception:
        return not _update_rate_in_memory(token_id, limit)


async def auth_middleware(request: Request, call_next):
    public_paths = {"/", "/api/v1/health", "/api/v1/metrics", "/docs", "/openapi.json", "/redoc"}
    if request.url.path in public_paths:
        return await call_next(request)

    token = request.headers.get("X-API-Token")
    if not token:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": {"code": "UNAUTHORIZED", "message": "Missing API token"}},
        )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ApiToken).where(ApiToken.token == token, ApiToken.is_active == True))
        api_token = result.scalar_one_or_none()
        if not api_token:
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": {"code": "UNAUTHORIZED", "message": "Invalid or expired API token"}},
            )
        if api_token.expires_at and api_token.expires_at < datetime.now(timezone.utc):
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": {"code": "UNAUTHORIZED", "message": "Token expired"}},
            )

        # Rate limiting
        if await _is_rate_limited(str(api_token.id), api_token.rate_limit_per_minute):
            return JSONResponse(
                status_code=429,
                content={"success": False, "error": {"code": "RATE_LIMITED", "message": "Rate limit exceeded"}},
            )

        # Обновляем last_used_at не чаще раза в минуту
        now = datetime.now(timezone.utc)
        if api_token.last_used_at is None or now - api_token.last_used_at > timedelta(minutes=1):
            await db.execute(
                update(ApiToken).where(ApiToken.id == api_token.id).values(last_used_at=now)
            )
            await db.commit()

    # Идемпотентность для мутирующих методов
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        idem_key = request.headers.get("Idempotency-Key")
        if idem_key:
            try:
                key_uuid = uuid.UUID(idem_key)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": {"code": "BAD_REQUEST", "message": "Invalid Idempotency-Key format"}},
                )
            async with AsyncSessionLocal() as db:
                existing = await db.execute(
                    select(IdempotencyKey).where(IdempotencyKey.key == key_uuid)
                )
                existing = existing.scalar_one_or_none()
                if existing:
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=existing.response_body,
                    )

            response = await call_next(request)

            # Сохраняем ответ для повторных запросов
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            try:
                json_body = json.loads(body)
            except Exception:
                json_body = {"success": True, "data": None}

            async with AsyncSessionLocal() as db:
                idem = IdempotencyKey(
                    key=key_uuid,
                    response_status=response.status_code,
                    response_body=json_body,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                )
                db.add(idem)
                await db.commit()

            return Response(content=body, status_code=response.status_code, headers=dict(response.headers))

    response = await call_next(request)
    return response
