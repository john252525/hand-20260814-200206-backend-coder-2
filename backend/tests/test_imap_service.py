import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.imap_service import fetch_unseen_emails


@pytest.mark.asyncio
async def test_fetch_unseen_emails_empty_when_no_settings(setup_db):
    from app.core.config import settings
    old_host = settings.imap_host
    old_user = settings.imap_user
    settings.imap_host = ""
    settings.imap_user = ""
    result = await fetch_unseen_emails()
    assert result == []
    settings.imap_host = old_host
    settings.imap_user = old_user


@pytest.mark.asyncio
async def test_fetch_unseen_emails_with_attachment(setup_db, tmp_path):
    from app.core.config import settings
    settings.imap_host = "imap.test.com"
    settings.imap_user = "test@test.com"
    settings.imap_password = "pass"
    settings.upload_dir = str(tmp_path)

    # Строим сырое письмо с вложением
    import email
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication

    msg = MIMEMultipart()
    msg["From"] = "test@test.com"
    msg["Subject"] = "Test"
    msg.attach(MIMEText("Body"))
    attachment = MIMEApplication(b"file-content", _subtype="txt")
    attachment.add_header("Content-Disposition", "attachment", filename="file.txt")
    msg.attach(attachment)

    raw = msg.as_bytes()

    mock_client = MagicMock()
    mock_client.wait_hello_from_server = AsyncMock()
    mock_client.login = AsyncMock()
    mock_client.select = AsyncMock(return_value=(None, None))
    mock_client.search = AsyncMock(return_value=("OK", [b"1"]))
    mock_client.fetch = AsyncMock(return_value=("OK", [(None, raw)]))
    mock_client.store = AsyncMock()
    mock_client.logout = AsyncMock()

    with patch("aioimaplib.IMAP4_SSL", return_value=mock_client):
        result = await fetch_unseen_emails()
        assert len(result) == 1
        assert result[0]["subject"] == "Test"
        assert result[0]["body"] == "Body"
        assert len(result[0]["attachments"]) == 1
        assert "file.txt" in result[0]["attachments"][0]
