import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_category(client: AsyncClient, api_token: str):
    response = await client.post(
        "/api/v1/categories",
        json={"name": "Оргтехника", "description": "Компьютеры, принтеры", "keywords": ["ПК", "ноутбук"]},
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 201
    assert response.json()["data"]["name"] == "Оргтехника"


@pytest.mark.asyncio
async def test_list_categories(client: AsyncClient, api_token: str):
    # Создаем одну категорию
    await client.post(
        "/api/v1/categories",
        json={"name": "Мебель", "description": "Столы, стулья"},
        headers={"X-API-Token": api_token},
    )
    response = await client.get("/api/v1/categories", headers={"X-API-Token": api_token})
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert len(response.json()["data"]) >= 1


@pytest.mark.asyncio
async def test_get_category(client: AsyncClient, api_token: str):
    create_resp = await client.post(
        "/api/v1/categories",
        json={"name": "Кабель", "description": "Витая пара"},
        headers={"X-API-Token": api_token},
    )
    cat_id = create_resp.json()["data"]["id"]
    response = await client.get(f"/api/v1/categories/{cat_id}", headers={"X-API-Token": api_token})
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Кабель"


@pytest.mark.asyncio
async def test_update_category(client: AsyncClient, api_token: str):
    create_resp = await client.post(
        "/api/v1/categories",
        json={"name": "Старое имя", "description": "Описание"},
        headers={"X-API-Token": api_token},
    )
    cat_id = create_resp.json()["data"]["id"]
    response = await client.patch(
        f"/api/v1/categories/{cat_id}",
        json={"name": "Новое имя"},
        headers={"X-API-Token": api_token},
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Новое имя"


@pytest.mark.asyncio
async def test_delete_category(client: AsyncClient, api_token: str):
    create_resp = await client.post(
        "/api/v1/categories",
        json={"name": "Удаляемая", "description": "Описание"},
        headers={"X-API-Token": api_token},
    )
    cat_id = create_resp.json()["data"]["id"]
    response = await client.delete(f"/api/v1/categories/{cat_id}", headers={"X-API-Token": api_token})
    assert response.status_code == 200
    assert response.json()["success"] is True
