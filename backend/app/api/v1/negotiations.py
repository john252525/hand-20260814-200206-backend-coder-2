import uuid
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models import Tender, Task, LotSupplier
from app.services.settings_service import get_section
from app.services.webhook_integration import notify_negotiation_step
from app.workers.negotiate import negotiate_tender

router = APIRouter()

class NegotiatePayload(BaseModel):
    action: str = 'request_clarification'
    target_supplier_ids: list[UUID] = []
    custom_instructions: Optional[str] = None

@router.post('/{tender_id}/negotiate', status_code=202)
async def negotiate(
    tender_id: UUID,
    payload: NegotiatePayload,
    db: AsyncSession = Depends(get_db),
):
    if payload.action not in ('request_clarification', 'request_discount'):
        raise HTTPException(status_code=400, detail={'code': 'BAD_REQUEST', 'message': "action must be 'request_clarification' or 'request_discount'"})
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})

    # Защита от параллельных задач переговоров
    existing_task = (await db.execute(
        select(Task).where(
            Task.entity_type == 'tender',
            Task.entity_id == tender_id,
            Task.task_type == 'NEGOTIATE',
            Task.status.in_(['PENDING', 'IN_PROGRESS']),
        )
    )).scalar_one_or_none()
    if existing_task:
        raise HTTPException(status_code=409, detail={'code': 'CONFLICT', 'message': 'Negotiation already in progress'})

    task = Task(
        task_type='NEGOTIATE',
        status='PENDING',
        entity_type='tender',
        entity_id=tender_id,
        input_data=payload.model_dump(mode='json'),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    celery_task = negotiate_tender.delay(
        str(tender_id), str(task.id), payload.action,
        [str(s) for s in payload.target_supplier_ids], payload.custom_instructions
    )
    task.celery_task_id = celery_task.id
    await db.commit()
    return {'success': True, 'data': {'task_id': task.id, 'status': 'ACCEPTED', 'check_url': f'/api/v1/tasks/{task.id}'}}

@router.get('/{tender_id}/negotiation-status')
async def negotiation_status(tender_id: UUID, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    result = await db.execute(
        select(LotSupplier)
        .where(LotSupplier.tender_id == tender_id)
        .options(
            selectinload(LotSupplier.supplier),
            selectinload(LotSupplier.commercial_offers),
        )
    )
    lot_suppliers = result.scalars().all()
    statuses = [ls.status for ls in lot_suppliers]
    if any(s == 'NEGOTIATING' for s in statuses):
        result_status = 'IN_PROGRESS'
    elif any(s in ('CP_REQUESTED', 'CP_PARTIALLY_RECEIVED', 'CP_FULLY_RECEIVED', 'RESPONDED') for s in statuses):
        result_status = 'NOT_STARTED'
    else:
        result_status = 'COMPLETED'

    suppliers_info = []
    for ls in lot_suppliers:
        offers = list(ls.commercial_offers)
        offers.sort(key=lambda o: o.created_at)
        best_margin = None
        initial_margin = None
        if offers:
            margins = [o.margin_percent for o in offers if o.margin_percent is not None]
            if margins:
                best_margin = max(margins)
                initial_margin = margins[0]
        suppliers_info.append({
            'supplier_id': ls.supplier_id,
            'supplier_name': ls.supplier.name if ls.supplier else None,
            'initial_margin_percent': initial_margin,
            'current_margin_percent': best_margin,
            'improvement_percent': (best_margin - initial_margin) if (best_margin is not None and initial_margin is not None) else None,
            'status': ls.status,
            'last_action': None,
            'last_action_at': None,
        })

    # Получаем количество циклов из последней задачи и max_cycles из настроек
    from app.models import Task as TaskModel
    last_task = (await db.execute(
        select(TaskModel).where(
            TaskModel.entity_type == 'tender',
            TaskModel.entity_id == tender_id,
            TaskModel.task_type == 'NEGOTIATE',
            TaskModel.status == 'COMPLETED',
        ).order_by(TaskModel.completed_at.desc()).limit(1)
    )).scalar_one_or_none()
    cycles = last_task.output_data.get('cycles_completed', 0) if last_task and last_task.output_data else 0
    comm_settings = await get_section(db, 'communication')
    max_cycles = comm_settings.get('max_clarification_cycles', 2)

    return {
        'success': True,
        'data': {
            'status': result_status,
            'cycles_completed': cycles,
            'max_cycles': max_cycles,
            'started_at': last_task.created_at if last_task else None,
            'suppliers': suppliers_info,
        },
    }
