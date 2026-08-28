import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_missing_token(client: AsyncClient):
    response = await client.get("/api/v1/tokens")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token(client: AsyncClient):
    response = await client.get("/api/v1/tokens", headers={"X-API-Token": "invalid"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rate_limit(client: AsyncClient, api_token: str):
    # Создаем токен с лимитом 2
    create_resp = await client.post(
        "/api/v1/tokens",
        json={"rate_limit_per_minute": 2},
        headers={"X-API-Token": api_token},
    )
    limited_token = create_resp.json()["data"]["token"]
    limited_id = create_resp.json()["data"]["id"]

    for _ in range(2):
        resp = await client.get("/api/v1/tokens", headers={"X-API-Token": limited_token})
        assert resp.status_code == 200

    resp = await client.get("/api/v1/tokens", headers={"X-API-Token": limited_token})
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_idempotency(client: AsyncClient, api_token: str):
    idem_key = str(uuid.uuid4())
    payload = {"description": "idem"}
    headers = {"X-API-Token": api_token, "Idempotency-Key": idem_key}
    resp1 = await client.post("/api/v1/tokens", json=payload, headers=headers)
    assert resp1.status_code == 201
    resp2 = await client.post("/api/v1/tokens", json=payload, headers=headers)
    assert resp2.status_code == resp1.status_code
    assert resp2.json() == resp1.json()
