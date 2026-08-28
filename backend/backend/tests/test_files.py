import io
from decimal import Decimal

import pytest
from fastapi import UploadFile

from app.core.database import AsyncSessionLocal
from app.models import File
from app.api.v1.files import upload_file, download_file, delete_file


@pytest.mark.asyncio
async def test_upload_download_delete(client, api_token, setup_db, tmp_path):
    from app.core.config import settings
    settings.upload_dir = str(tmp_path)

    file_content = b"test content"
    # Передаём обязательный entity_id как query-параметр
    resp = await client.post(
        "/api/v1/files/upload?entity_type=tender&entity_id=123e4567-e89b-12d3-a456-426614174000",
        files={"file": ("test.txt", file_content, "text/plain")},
        headers={"X-API-Token": api_token},
    )
    assert resp.status_code == 201
    file_id = resp.json()["data"]["id"]

    download = await client.get(f"/api/v1/files/{file_id}/download", headers={"X-API-Token": api_token})
    assert download.status_code == 200
    assert download.content == file_content

    delete = await client.delete(f"/api/v1/files/{file_id}", headers={"X-API-Token": api_token})
    assert delete.status_code == 200
