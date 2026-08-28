import json
import os
from datetime import datetime, timezone
from typing import List, Optional
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models import Tender, TenderDocument, TenderPosition, TenderRequirement
from app.services.llm_service import chat_completion

logger = structlog.get_logger(__name__)

SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.xlsx', '.txt', '.csv'}

async def extract_text_from_file(file_path: str, mime_type: str = "") -> str:
    """Извлекает текст из файла. Поддерживает PDF, DOCX, XLSX, TXT."""
    if not os.path.exists(file_path):
        return ""
    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
    if ext not in SUPPORTED_EXTENSIONS:
        return ""
    try:
        if ext == 'pdf':
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        elif ext == 'docx':
            from docx import Document
            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs)
        elif ext == 'xlsx':
            import openpyxl
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            texts = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    texts.append(" ".join(str(c) for c in row if c is not None))
            return "\n".join(texts)
        else:  # txt, csv
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
    except Exception as e:
        logger.error("document_parser.extract_error", file=file_path, error=str(e))
        return ""

async def extract_tender_data(db: AsyncSession, tender: Tender) -> None:
    """Извлекает структурированные данные из всех документов тендера через LLM."""
    await db.execute(delete(TenderPosition).where(TenderPosition.tender_id == tender.id))
    await db.execute(delete(TenderRequirement).where(TenderRequirement.tender_id == tender.id))
    await db.flush()

    docs = tender.documents
    texts = []
    for doc in docs:
        if doc.storage_path and os.path.exists(doc.storage_path):
            text = await extract_text_from_file(doc.storage_path, doc.mime_type)
            doc.parsed_text = text
            doc.parse_status = "PARSED" if text else "ERROR"
            doc.parse_error = None if text else "Не удалось извлечь текст"
            if text:
                texts.append(text)
        else:
            doc.parse_status = "ERROR"
            doc.parse_error = "Файл не найден или не загружен на диск"

    combined_text = "\n\n".join(texts)[:12000]
    if not combined_text:
        return
    if not settings.llm_api_key:
        return

    prompt = f"""Ты — анализатор тендерной документации. Извлеки из предоставленного текста структурированные данные.
Текст документации:
{combined_text}
Извлеки строго в формате JSON:
{{
  "positions": [{{"position_number": 1, "name": "", "characteristics": "", "gost": "", "okpd2": "", "quantity": 1.0, "unit": "шт", "is_essential": true}}],
  "requirements": {{"delivery_date": "YYYY-MM-DD или null", "delivery_address": "", "delivery_conditions": "", "license_required": false, "sro_required": false, "security_bid": null, "security_contract": null, "prepayment_percent": null, "stages_count": 1, "special_conditions": []}}
}}
Если какой-то параметр не указан — ставь null или значение по умолчанию.
Ответ — ТОЛЬКО JSON."""

    response = await chat_completion(prompt)
    if not response:
        tender.processing_error = "LLM вернул пустой ответ"
        return

    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        logger.error("document_parser.invalid_json", error=str(e))
        tender.processing_error = "LLM вернул некорректный JSON"
        return

    # Валидация
    positions = data.get("positions", [])
    if not isinstance(positions, list) or len(positions) == 0:
        tender.processing_error = "LLM не извлёк позиции"
        return

    for p in positions:
        if not isinstance(p, dict) or not p.get("name") or not p.get("quantity"):
            tender.processing_error = "Позиция содержит некорректные данные"
            return
        try:
            qty = float(p["quantity"])
        except (TypeError, ValueError):
            tender.processing_error = "Количество не является числом"
            return
        if qty <= 0:
            tender.processing_error = "Количество должно быть больше нуля"
            return

    tender.structured_data = data
    for idx, p in enumerate(positions, 1):
        tp = TenderPosition(
            tender_id=tender.id,
            position_number=p.get("position_number", idx),
            name=p.get("name", ""),
            characteristics=p.get("characteristics", ""),
            gost=p.get("gost", ""),
            okpd2=p.get("okpd2", ""),
            quantity=p.get("quantity") or 0,
            unit=p.get("unit", "шт"),
            is_essential=p.get("is_essential", True),
        )
        db.add(tp)

    req_data = data.get("requirements", {})
    req = TenderRequirement(
        tender_id=tender.id,
        delivery_date=datetime.fromisoformat(req_data["delivery_date"]) if req_data.get("delivery_date") else None,
        delivery_address=req_data.get("delivery_address", ""),
        delivery_conditions=req_data.get("delivery_conditions", ""),
        license_required=req_data.get("license_required", False),
        sro_required=req_data.get("sro_required", False),
        security_bid=req_data.get("security_bid"),
        security_contract=req_data.get("security_contract"),
        prepayment_percent=req_data.get("prepayment_percent"),
        stages_count=req_data.get("stages_count", 1),
        special_conditions=req_data.get("special_conditions", []),
    )
    db.add(req)
    await db.flush()