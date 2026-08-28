import asyncio
import email
import os
import uuid
from email.header import decode_header
from typing import List, Dict, Any

from app.core.config import settings


async def fetch_unseen_emails() -> List[Dict[str, Any]]:
    """Получение непрочитанных писем из IMAP."""
    if not settings.imap_host or not settings.imap_user:
        return []

    import aioimaplib

    emails = []
    client = aioimaplib.IMAP4_SSL(host=settings.imap_host, port=settings.imap_port)
    try:
        await client.wait_hello_from_server()
        await client.login(settings.imap_user, settings.imap_password)
        await client.select("INBOX")
        _, data = await client.search("UNSEEN")
        for raw_num in data[0].split():
            num = raw_num.decode()
            try:
                typ, msg_data = await client.fetch(num, "(RFC822)")
                if typ != "OK":
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = _decode_header_value(msg.get("Subject", ""))
                from_ = _decode_header_value(msg.get("From", ""))
                message_id = msg.get("Message-ID", "")
                in_reply_to = msg.get("In-Reply-To", "")

                body = _get_email_body(msg)

                attachments = []
                for part in msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue
                    filename = part.get_filename()
                    if filename:
                        filename = _decode_header_value(filename)
                        data = part.get_payload(decode=True)
                        if data:
                            path = os.path.join(settings.upload_dir, "attachments", f"{uuid.uuid4().hex}_{filename}")
                            os.makedirs(os.path.dirname(path), exist_ok=True)
                            with open(path, "wb") as f:
                                f.write(data)
                            attachments.append(path)

                emails.append({
                    "message_id": message_id,
                    "in_reply_to": in_reply_to,
                    "from_": from_,
                    "subject": subject,
                    "body": body,
                    "attachments": attachments,
                })

                await client.store(num, "+FLAGS", "\\Seen")
            except Exception as e:
                print(f"Error processing email {num}: {e}")
                continue

        await client.logout()
    except Exception as e:
        print(f"IMAP error: {e}")
        return []

    return emails


def _decode_header_value(value: str) -> str:
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = ""
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(charset or "utf-8", errors="replace")
        else:
            result += part
    return result


def _get_email_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return part.get_payload(decode=True).decode("utf-8", errors="replace")
        return ""
    return msg.get_payload(decode=True).decode("utf-8", errors="replace") if msg.get_payload(decode=True) else ""
