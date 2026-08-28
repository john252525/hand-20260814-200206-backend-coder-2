import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import click
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import ApiToken


@click.group()
def token():
    """Управление API-токенами"""
    pass


@token.command("create")
@click.option("--description", default="", help="Описание токена")
@click.option("--rate-limit", default=60, show_default=True, help="Лимит запросов в минуту")
@click.option("--expires-in-days", type=int, default=None, help="Срок действия в днях")
def create_token(description: str, rate_limit: int, expires_in_days: Optional[int]):
    """Создать новый API-токен"""
    async def _create():
        async with AsyncSessionLocal() as db:
            token_value = uuid.uuid4().hex
            expires_at = None
            if expires_in_days:
                expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
            api_token = ApiToken(
                token=token_value,
                description=description,
                rate_limit_per_minute=rate_limit,
                expires_at=expires_at,
            )
            db.add(api_token)
            await db.commit()
            await db.refresh(api_token)
            click.echo(f"Token created: {token_value}")
            click.echo(f"ID: {api_token.id}")
            click.echo(f"Description: {api_token.description}")
            click.echo(f"Expires at: {api_token.expires_at}")

    asyncio.run(_create())


@token.command("revoke")
@click.argument("token_id")
def revoke_token(token_id: str):
    """Деактивировать токен по ID"""
    async def _revoke():
        async with AsyncSessionLocal() as db:
            api_token = await db.get(ApiToken, uuid.UUID(token_id))
            if not api_token:
                raise click.ClickException(f"Token {token_id} not found")
            api_token.is_active = False
            await db.commit()
            click.echo(f"Token {token_id} revoked")

    asyncio.run(_revoke())


@token.command("list")
def list_tokens():
    """Список токенов"""
    async def _list():
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ApiToken).order_by(ApiToken.created_at.desc()))
            tokens = result.scalars().all()
            for t in tokens:
                click.echo(f"{t.id} | {t.token[:4]}...{t.token[-4:]} | active={t.is_active} | desc={t.description}")

    asyncio.run(_list())


if __name__ == "__main__":
    token()
