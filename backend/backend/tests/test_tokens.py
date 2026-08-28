import uuid

import pytest

from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_token(client: AsyncClient, api_token: str):
    response = await client.post(
        "/api/v1/tokens",
        json={"description": "test", "rate_limit_per_minute": 10},
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["description"] == "test"
    assert len(data["token"]) == 32


@pytest.mark.asyncio
async def test_list_tokens(client: AsyncClient, api_token: str):
    response = await client.get("/api/v1/tokens", headers={"X-API-Token": api_token})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "meta" in response.json()


@pytest.mark.asyncio
async def test_delete_token(client: AsyncClient, api_token: str):
    # Создаем токен
    create_resp = await client.post(
        "/api/v1/tokens",
        json={"description": "to_delete"},
        headers={"X-API-Token": api_token},
    )
    token_id = create_resp.json()["data"]["id"]
    delete_resp = await client.delete(f"/api/v1/tokens/{token_id}", headers={"X-API-Token": api_token})
    assert delete_resp.status_code == 200
    assert delete_resp.json()["success"] is True


@pytest.mark.asyncio
async def test_unauthorized(client: AsyncClient):
    response = await client.get("/api/v1/tokens")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
