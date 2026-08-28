import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_all_settings(client: AsyncClient, api_token: str):
    response = await client.get("/api/v1/settings", headers={"X-API-Token": api_token})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "company" in response.json()["data"]


@pytest.mark.asyncio
async def test_update_section(client: AsyncClient, api_token: str):
    response = await client.put(
        "/api/v1/settings/scoring",
        json={"min_total_score": 70},
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 200
    assert response.json()["data"]["min_total_score"] == 70


@pytest.mark.asyncio
async def test_create_section_via_put(client: AsyncClient, api_token: str):
    response = await client.put(
        "/api/v1/settings/new_section",
        json={"key1": "value1"},
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 200
    assert response.json()["data"]["key1"] == "value1"
