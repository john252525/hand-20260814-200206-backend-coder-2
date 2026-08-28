import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import ApiToken

router = APIRouter()


class TokenCreate(BaseModel):
    description: str = ""
    rate_limit_per_minute: int = 60
    expires_in_days: Optional[int] = None

    @property
    def validate_expiry(self):
        if self.expires_in_days is not None and self.expires_in_days <= 0:
            raise ValueError("expires_in_days must be positive")
        return self


class TokenUpdate(BaseModel):
    description: Optional[str] = None
    is_active: Optional[bool] = None
    rate_limit_per_minute: Optional[int] = None
    expires_at: Optional[datetime] = None


class TokenRead(BaseModel):
    id: uuid.UUID
    description: str
    token_preview: str
    is_active: bool
    rate_limit_per_minute: int
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenReadWithToken(BaseModel):
    id: uuid.UUID
    token: str
    description: str
    rate_limit_per_minute: int
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("")
async def list_tokens(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total = await db.scalar(select(func.count()).select_from(ApiToken))
    result = await db.execute(select(ApiToken).offset((page - 1) * per_page).limit(per_page))
    tokens = result.scalars().all()
    return {
        "success": True,
        "data": [
            TokenRead(
                id=t.id,
                description=t.description,
                token_preview=t.token[:4] + "..." + t.token[-4:],
                is_active=t.is_active,
                rate_limit_per_minute=t.rate_limit_per_minute,
                last_used_at=t.last_used_at,
                expires_at=t.expires_at,
                created_at=t.created_at,
            )
            for t in tokens
        ],
        "meta": {"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
    }


@router.post("", status_code=201)
async def create_token(
    payload: TokenCreate,
    db: AsyncSession = Depends(get_db),
):
    if payload.expires_in_days is not None and payload.expires_in_days <= 0:
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "expires_in_days must be positive"})
    token_value = uuid.uuid4().hex
    expires_at = None
    if payload.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
    token = ApiToken(
        token=token_value,
        description=payload.description,
        rate_limit_per_minute=payload.rate_limit_per_minute,
        expires_at=expires_at,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return {
        "success": True,
        "data": TokenReadWithToken(
            id=token.id,
            token=token.token,
            description=token.description,
            rate_limit_per_minute=token.rate_limit_per_minute,
            created_at=token.created_at,
        ),
    }


@router.patch("/{token_id}")
async def update_token(
    token_id: uuid.UUID,
    payload: TokenUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.get(ApiToken, token_id)
    if not result:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Token not found"})
    if payload.description is not None:
        result.description = payload.description
    if payload.is_active is not None:
        result.is_active = payload.is_active
    if payload.rate_limit_per_minute is not None:
        result.rate_limit_per_minute = payload.rate_limit_per_minute
    if payload.expires_at is not None:
        result.expires_at = payload.expires_at
    await db.commit()
    await db.refresh(result)
    return {
        "success": True,
        "data": TokenRead(
            id=result.id,
            description=result.description,
            token_preview=result.token[:4] + "..." + result.token[-4:],
            is_active=result.is_active,
            rate_limit_per_minute=result.rate_limit_per_minute,
            last_used_at=result.last_used_at,
            expires_at=result.expires_at,
            created_at=result.created_at,
        ),
    }


@router.delete("/{token_id}")
async def delete_token(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.get(ApiToken, token_id)
    if not result:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Token not found"})
    await db.delete(result)
    await db.commit()
    return {"success": True, "data": None}
