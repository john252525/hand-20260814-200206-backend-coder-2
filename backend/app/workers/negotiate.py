import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.core.database import AsyncSessionLocal
from app.models import CommercialOffer, Communication, LotSupplier, Tender, Task
from app.services.negotiation_service import request_clarification, request_discount, get_competitive_prices
from app.services.settings_service import get_section
from app.services.tender_status_service import change_tender_status
from app.services.webhook_integration import notify_negotiation_step
from app.workers.celery_app import celery_app

async def _count_communications_by_type(db, lot_supplier_id, message_type):
    return await db.scalar(
        select(func.count()).select_from(Communication).where(
            Communication.lot_supplier_id == lot_supplier_id,
            Communication.message_type == message_type,
        )
    ) or 0

async def _count_negotiation_communications_by_tender(db, tender_id):
    return await db.scalar(
        select(func.count()).select_from(Communication).where(
            Communication.tender_id == tender_id,
            Communication.message_type.in_(['clarification', 'discount_request']),
        )
    ) or 0

@celery_app.task(name='negotiate_tender', bind=True)
def negotiate_tender(
    self,
    tender_id: str,
    task_id: str | None = None,
    action: str = 'request_clarification',
    target_supplier_ids: list[str] | None = None,
    custom_instructions: str | None = None,
) -> dict:
    try:
        asyncio.run(_negotiate(tender_id, task_id, action, target_supplier_ids or [], custom_instructions))
        return {'status': 'completed'}
    except Exception as e:
        if task_id:
            asyncio.run(_update_task_error(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)

async def _update_task_error(task_id: str, error: str):
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        if task:
            task.status = 'FAILED'
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

async def _get_last_valid_offer(offers, action: str):
    valid = []
    for o in sorted(offers, key=lambda x: x.created_at, reverse=True):
        if action == 'request_clarification' and o.clarification_needed and o.status in ('PARTIAL', 'NONE', 'ERROR'):
            valid.append(o)
        elif action == 'request_discount' and not o.clarification_needed and o.status == 'FULL':
            valid.append(o)
    return valid[0] if valid else None

async def _negotiate(
    tender_id: str,
    task_id: str | None = None,
    action: str = 'request_clarification',
    target_supplier_ids: list[str] | None = None,
    custom_instructions: str | None = None,
):
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id)) if task_id else None
        if task:
            task.status = 'IN_PROGRESS'
            await db.commit()
        tender = await db.get(Tender, UUID(tender_id))
        if not tender:
            return
        comm_settings = await get_section(db, 'communication')
        max_clarif = comm_settings.get('max_clarification_cycles', 2)
        max_disc = comm_settings.get('max_discount_requests_per_supplier', 2)
        query = select(LotSupplier).where(
            LotSupplier.tender_id == tender.id,
            LotSupplier.status.notin_(['DECLINED', 'NO_RESPONSE']),
        )
        if target_supplier_ids:
            supplier_uuids = [UUID(s) for s in target_supplier_ids]
            query = query.where(LotSupplier.supplier_id.in_(supplier_uuids))
        result = await db.execute(query.options(selectinload(LotSupplier.commercial_offers)))
        lot_suppliers = result.scalars().all()

        # Если активных поставщиков нет — переводим тендер в NO_SUPPLIERS_FOUND
        if not lot_suppliers:
            if tender.status not in ('NO_SUPPLIERS_FOUND', 'READY_FOR_DECISION', 'APPROVED', 'REJECTED'):
                await change_tender_status(db, tender, 'NO_SUPPLIERS_FOUND', note='Все поставщики отказались или недоступны')
                await db.commit()
            return

        processed = 0
        sent_any = False
        # Флаг, что все активные поставщики не требуют дальнейших действий
        all_finished = True

        for ls in lot_suppliers:
            offers = list(ls.commercial_offers)
            if not offers:
                all_finished = False
                continue
            offer = await _get_last_valid_offer(offers, action)
            if not offer:
                # Если нет подходящего КП, считаем поставщика завершённым (нечего отправлять)
                continue
            if action == 'request_clarification':
                existing = await _count_communications_by_type(db, ls.id, 'clarification')
                if existing >= max_clarif:
                    ls.status = 'NO_RESPONSE'
                    continue  # поставщик завершён, all_finished остаётся True
                await request_clarification(db, ls, offer, custom_instructions)
                await notify_negotiation_step(tender.id, ls.supplier_id, 'clarification')
                processed += 1
                sent_any = True
                all_finished = False
            elif action == 'request_discount':
                existing = await _count_communications_by_type(db, ls.id, 'discount_request')
                if existing >= max_disc:
                    ls.status = 'NO_RESPONSE'
                    continue
                competitive = await get_competitive_prices(db, tender.id, offer.id)
                if competitive:
                    await request_discount(db, ls, offer, competitive, custom_instructions)
                    await notify_negotiation_step(tender.id, ls.supplier_id, 'discount_request')
                    processed += 1
                    sent_any = True
                    all_finished = False
                else:
                    # Нет конкурентных цен — переговоры не требуются, поставщик остаётся как есть
                    pass

        if sent_any and tender.status not in ('NEGOTIATING', 'READY_FOR_DECISION', 'APPROVED', 'REJECTED'):
            await change_tender_status(db, tender, 'NEGOTIATING', note='Переговоры начаты')
        if all_finished:
            if tender.status not in ('READY_FOR_DECISION', 'APPROVED', 'REJECTED'):
                await change_tender_status(db, tender, 'READY_FOR_DECISION', note='Переговоры завершены или не требуются')
        await db.commit()
        if task:
            cycles_total = await _count_negotiation_communications_by_tender(db, tender.id)
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = 'COMPLETED'
                task.output_data = {'processed': processed, 'cycles_completed': cycles_total, 'max_cycles': max_clarif}
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()

@celery_app.task(name='auto_negotiate')
def auto_negotiate() -> dict:
    asyncio.run(_auto_negotiate())
    return {'status': 'completed'}

async def _auto_negotiate():
    async with AsyncSessionLocal() as db:
        comm_settings = await get_section(db, 'communication')
        timeout_hours = comm_settings.get('response_timeout_hours', 48)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
        tenders_result = await db.execute(
            select(Tender).where(Tender.status.in_(['CP_REQUESTED', 'CP_PARTIALLY_RECEIVED', 'CP_FULLY_RECEIVED', 'NEGOTIATING']))
        )
        for tender in tenders_result.scalars().all():
            last_comm = await db.scalar(
                select(Communication.sent_at)
                .where(Communication.tender_id == tender.id, Communication.direction == 'outgoing')
                .order_by(Communication.sent_at.desc())
                .limit(1)
            )
            if last_comm and last_comm < cutoff:
                ls_result = await db.execute(
                    select(LotSupplier).where(LotSupplier.tender_id == tender.id).options(selectinload(LotSupplier.commercial_offers))
                )
                lot_suppliers = ls_result.scalars().all()
                needs_clarification = any(
                    any(o.clarification_needed for o in ls.commercial_offers)
                    for ls in lot_suppliers
                    if ls.status not in ('DECLINED', 'NO_RESPONSE')
                )
                if needs_clarification:
                    await _negotiate(str(tender.id), None, 'request_clarification')
                else:
                    await _negotiate(str(tender.id), None, 'request_discount')
