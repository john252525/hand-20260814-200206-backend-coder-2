from io import BytesIO
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Tuple
import structlog
import openpyxl
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models import Tender, Supplier, LotSupplier, Communication
from app.services.settings_service import get_section

logger = structlog.get_logger(__name__)

def build_positions_table(tender: Tender) -> str:
    positions = tender.positions
    if not positions:
        return "Нет данных о позициях"
    lines = ["№\tНаименование\tХарактеристики\tКоличество\tЕд. изм.\tЦена за ед.\tСрок поставки"]
    for i, p in enumerate(positions, 1):
        lines.append(f"{i}\t{p.name}\t{p.characteristics}\t{p.quantity}\t{p.unit}\t\t")
    return "\n".join(lines)

def build_positions_excel(tender: Tender) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Позиции"
    ws.append(["№", "Наименование", "Характеристики", "Количество", "Ед. изм.", "Цена за ед.", "Срок поставки"])
    for i, p in enumerate(tender.positions, 1):
        ws.append([i, p.name, p.characteristics, float(p.quantity), p.unit, "", ""])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()

async def generate_cp_request_email(tender: Tender, db: AsyncSession) -> Tuple[str, str]:
    templates = await get_section(db, "templates")
    cp_request = templates.get("cp_request", {})
    subject_template = cp_request.get("subject", "Запрос коммерческого предложения: {lot_name}")
    body_template = cp_request.get("body", "Добрый день!\n\nПрошу предоставить коммерческое предложение по следующим позициям:\n\n{positions_table}\n\n{company_signature}")
    company = await get_section(db, "company")
    company_signature = (
        f"{company.get('email_signature', '')}\n"
        f"{company.get('contact_person', '')}\n"
        f"{company.get('legal_name', '')}\n"
        f"{company.get('contact_phone', '')}\n"
        f"{company.get('contact_email', '')}"
    ).strip()
    subject = subject_template.replace("{lot_name}", tender.title)
    body = body_template.replace("{positions_table}", build_positions_table(tender))
    body = body.replace("{deadline_date}", tender.deadline_at.strftime("%d.%m.%Y") if tender.deadline_at else "не указан")
    body = body.replace("{total_quantity}", str(sum(p.quantity for p in tender.positions)))
    body = body.replace("{company_signature}", company_signature)
    body = body.replace("{nmck}", str(tender.nmck) if tender.nmck else "")
    return subject, body

async def send_cp_request_to_supplier(
    db: AsyncSession,
    tender: Tender,
    supplier: Supplier,
    lot_supplier: LotSupplier,
) -> Communication:
    subject, body = await generate_cp_request_email(tender, db)
    excel_bytes = build_positions_excel(tender)
    simulated = False
    if settings.smtp_host and settings.smtp_user and supplier.email:
        try:
            import aiosmtplib
            msg = EmailMessage()
            msg["From"] = settings.smtp_user
            msg["To"] = supplier.email
            msg["Subject"] = subject
            msg.set_content(body)
            msg.add_attachment(
                excel_bytes,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename="positions.xlsx",
            )
            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                start_tls=settings.smtp_use_tls,
                username=settings.smtp_user,
                password=settings.smtp_password,
            )
        except Exception:
            simulated = True
    else:
        simulated = True
    communication = Communication(
        lot_supplier_id=lot_supplier.id,
        tender_id=tender.id,
        direction="outgoing",
        channel="email",
        subject=subject,
        body_text=body + ("\n\n[SMTP не настроен — письмо не отправлено]" if simulated else ""),
        message_type="cp_request",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(communication)
    lot_supplier.status = "CP_REQUESTED"
    await db.flush()
    logger.info("communication.sent", communication_id=str(communication.id), supplier_id=str(supplier.id), tender_id=str(tender.id), message_type="cp_request")
    return communication