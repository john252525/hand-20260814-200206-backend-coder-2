import asyncio
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.core.database import AsyncSessionLocal
from app.models import CommercialOffer, Communication, LotSupplier, Task, Tender
from app.services.negotiation_service import request_clarification, request_discount, get_competitive_prices
from app.services.tender_status_service import change_tender_status
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
        from app.services.settings_service import get_section
        comm_settings = await get_section(db, 'communication')
        max_clarif = comm_settings.get('max_clarification_cycles', 2)
        max_disc = comm_settings.get('max_discount_requests_per_supplier', 2)

        # Загружаем lot_suppliers с offer
        query = select(LotSupplier).where(
            LotSupplier.tender_id == tender.id,
            LotSupplier.status.notin_(['DECLINED', 'NO_RESPONSE']),
        )
        if target_supplier_ids:
            supplier_uuids = [UUID(s) for s in target_supplier_ids]
            query = query.where(LotSupplier.supplier_id.in_(supplier_uuids))
        result = await db.execute(query.options(selectinload(LotSupplier.commercial_offers)))
        lot_suppliers = result.scalars().all()
        processed = 0
        all_finished = True
        sent_any = False
        for ls in lot_suppliers:
            offers = list(ls.commercial_offers)
            if not offers:
                continue
            offer = max(offers, key=lambda o: o.created_at)
            if action == 'request_clarification' and offer.clarification_needed:
                existing = await _count_communications_by_type(db, ls.id, 'clarification')
                if existing >= max_clarif:
                    # лимит исчерпан - помечаем как не ответивший
                    ls.status = 'NO_RESPONSE'
                    continue
                await request_clarification(db, ls, offer, custom_instructions)
                processed += 1
                sent_any = True
                all_finished = False
            elif action == 'request_discount' and not offer.clarification_needed and offer.status == 'FULL':
                existing = await _count_communications_by_type(db, ls.id, 'discount_request')
                if existing >= max_disc:
                    ls.status = 'NO_RESPONSE'
                    continue
                competitive = await get_competitive_prices(db, tender.id, offer.id)
                if competitive:
                    await request_discount(db, ls, offer, competitive, custom_instructions)
                    processed += 1
                    sent_any = True
                    all_finished = False
        # Если отправлено переговорное письмо - переводим тендер в NEGOTIATING
        if sent_any and tender.status not in ('NEGOTIATING', 'READY_FOR_DECISION', 'APPROVED', 'REJECTED'):
            await change_tender_status(db, tender, 'NEGOTIATING', note='Переговоры начаты')
        # Если никто не может продолжать, переводим тендер в READY_FOR_DECISION
        if all_finished and lot_suppliers:
            if tender.status not in ('READY_FOR_DECISION', 'APPROVED', 'REJECTED'):
                await change_tender_status(db, tender, 'READY_FOR_DECISION', note='Максимальное число итераций переговоров достигнуто')
        await db.commit()
        if task:
            cycles_total = await _count_negotiation_communications_by_tender(db, tender.id)
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = 'COMPLETED'
                task.output_data = {'processed': processed, 'cycles_completed': cycles_total, 'max_cycles': 2}
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()


@celery_app.task(name='auto_negotiate')
def auto_negotiate() -> dict:
    """Периодическая задача: находит тендеры, где пора переходить к следующему шагу переговоров."""
    asyncio.run(_auto_negotiate())
    return {'status': 'completed'}


async def _auto_negotiate():
    from datetime import timedelta
    from app.services.settings_service import get_section
    async with AsyncSessionLocal() as db:
        comm_settings = await get_section(db, 'communication')
        timeout_hours = comm_settings.get('response_timeout_hours', 48)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
        # Ищем тендеры в статусе CP_REQUESTED/CP_PARTIALLY_RECEIVED/CP_FULLY_RECEIVED
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
                # Определяем, есть ли неполные КП
                ls_result = await db.execute(
                    select(LotSupplier).where(LotSupplier.tender_id == tender.id).options(selectinload(LotSupplier.commercial_offers))
                )
                lot_suppliers = ls_result.scalars().all()
                needs_clarification = any(
                    any(o.clarification_needed for o in ls.commercial_offers)
                    for ls in lot_suppliers
                    if ls.status not in ('DECLINED', 'NO_RESPONSE')
                )
                # Вызываем соответствующий шаг, но не оба сразу
                if needs_clarification:
                    await _negotiate(str(tender.id), None, 'request_clarification')
                else:
                    await _negotiate(str(tender.id), None, 'request_discount')
