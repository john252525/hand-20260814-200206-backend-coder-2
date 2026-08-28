import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models import Tender, TenderStatusHistory, LotSupplier, Supplier, Task, TenderPosition, TenderDocument, Communication, CommercialOffer, TenderSource, Category, Decision
from app.services.tender_status_service import change_tender_status
from app.services.webhook_integration import notify_tender_ready_for_decision

router = APIRouter()

class TenderCreate(BaseModel):
    source_id: Optional[uuid.UUID] = None
    source_tender_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=1000)
    description: str = ''
    nmck: Optional[Decimal] = None
    currency: str = 'RUB'
    published_at: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    customer_name: str = ''
    customer_inn: str = ''
    customer_kpp: str = ''
    platform: str = ''
    source_url: str = ''
    documents_urls: list[str] = []
    skip_auto_processing: bool = False
    @field_validator('deadline_at')
    @classmethod
    def validate_deadline(cls, v, info):
        published = info.data.get('published_at')
        if v and published and v <= published:
            raise ValueError('deadline_at must be after published_at')
        return v

class TenderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    nmck: Optional[Decimal] = None
    status: Optional[str] = None
    customer_name: Optional[str] = None

class SupplierConfirm(BaseModel):
    supplier_ids: list[uuid.UUID] = []
    new_suppliers: list[dict] = []
    source_by_id: dict[str, str] = {}

class RequestCpPayload(BaseModel):
    supplier_ids: list[uuid.UUID] = []
    template_override: Optional[dict] = None
    attach_positions_table: bool = True

class SearchSuppliersPayload(BaseModel):
    max_suppliers: int = 10
    channels: list[str] = ['google', 'internal_db']
    priority_order: list[str] = ['manufacturer', 'distributor', 'wholesaler']

class CommunicationSendPayload(BaseModel):
    supplier_id: uuid.UUID
    channel: str = 'email'
    subject: str = ''
    body: str = ''
    message_type: str = 'manual'
    attachments_file_ids: list[uuid.UUID] = []

async def _get_or_create_manual_source(db: AsyncSession) -> TenderSource:
    result = await db.execute(select(TenderSource).where(TenderSource.type == 'manual'))
    source = result.scalars().first()
    if source:
        return source
    source = TenderSource(
        name='Manual',
        type='manual',
        api_url='',
        config={},
    )
    db.add(source)
    await db.flush()
    return source

async def _tender_to_summary(t: Tender, include_description: bool = False) -> dict:
    best_margin = None
    for ls in t.lot_suppliers:
        offers = ls.commercial_offers
        for offer in offers:
            if offer.margin_percent is not None:
                best_margin = max(best_margin, offer.margin_percent) if best_margin is not None else offer.margin_percent
    return {
        'id': t.id,
        'source_tender_id': t.source_tender_id,
        'title': t.title,
        'description': t.description if include_description else (t.description[:300] if t.description else ''),
        'nmck': t.nmck,
        'currency': t.currency,
        'published_at': t.published_at,
        'deadline_at': t.deadline_at,
        'customer_name': t.customer_name,
        'customer_inn': t.customer_inn,
        'platform': t.platform,
        'status': t.status,
        'score': t.score,
        'matched_category_name': t.category.name if t.category else None,
        'similarity_score': t.similarity_score,
        'documents_count': len(t.documents),
        'positions_count': len(t.positions),
        'suppliers_count': len(t.lot_suppliers),
        'best_margin_percent': best_margin,
        'has_decision': bool(t.decisions),
        'created_at': t.created_at,
        'updated_at': t.updated_at,
    }

@router.get('')
async def list_tenders(
    status: Optional[str] = None,
    category_id: Optional[uuid.UUID] = None,
    source_id: Optional[uuid.UUID] = None,
    nmck_min: Optional[Decimal] = None,
    nmck_max: Optional[Decimal] = None,
    published_after: Optional[datetime] = None,
    published_before: Optional[datetime] = None,
    deadline_after: Optional[datetime] = None,
    deadline_before: Optional[datetime] = None,
    search: Optional[str] = None,
    has_score: Optional[bool] = None,
    score_min: Optional[float] = None,
    score_max: Optional[float] = None,
    sort_by: str = 'published_at',
    sort_order: str = 'desc',
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Tender).options(
        selectinload(Tender.category),
        selectinload(Tender.documents),
        selectinload(Tender.positions),
        selectinload(Tender.lot_suppliers).selectinload(LotSupplier.commercial_offers),
        selectinload(Tender.decisions),
    )
    if status:
        statuses = [s.strip() for s in status.split(',') if s.strip()]
        query = query.where(Tender.status.in_(statuses))
    if category_id:
        query = query.where(Tender.matched_category_id == category_id)
    if source_id:
        query = query.where(Tender.source_id == source_id)
    if nmck_min is not None:
        query = query.where(Tender.nmck >= nmck_min)
    if nmck_max is not None:
        query = query.where(Tender.nmck <= nmck_max)
    if published_after:
        query = query.where(Tender.published_at >= published_after)
    if published_before:
        query = query.where(Tender.published_at <= published_before)
    if deadline_after:
        query = query.where(Tender.deadline_at >= deadline_after)
    if deadline_before:
        query = query.where(Tender.deadline_at <= deadline_before)
    if search:
        query = query.where(Tender.title.ilike(f'%{search}%') | Tender.customer_name.ilike(f'%{search}%'))
    if has_score is not None:
        if has_score:
            query = query.where(Tender.score.isnot(None))
        else:
            query = query.where(Tender.score.is_(None))
    if score_min is not None:
        query = query.where(Tender.score >= score_min)
    if score_max is not None:
        query = query.where(Tender.score <= score_max)
    valid_sort = {'published_at', 'nmck', 'deadline', 'score', 'created_at'}
    if sort_by not in valid_sort:
        sort_by = 'published_at'
    sort_col = getattr(Tender, sort_by, Tender.published_at)
    if sort_order == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    tenders = result.scalars().all()
    data = [await _tender_to_summary(t) for t in tenders]
    return {
        'success': True,
        'data': data,
        'meta': {'page': page, 'per_page': per_page, 'total': total, 'pages': max(1, (total + per_page - 1) // per_page)},
    }

@router.post('', status_code=201)
async def create_tender(payload: TenderCreate, db: AsyncSession = Depends(get_db)):
    if payload.source_id is None:
        source = await _get_or_create_manual_source(db)
        source_id = source.id
    else:
        source = await db.get(TenderSource, payload.source_id)
        if not source:
            raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Source not found'})
        source_id = payload.source_id
    source_tender_id = payload.source_tender_id or str(uuid.uuid4())
    existing = await db.execute(select(Tender).where(Tender.source_id == source_id, Tender.source_tender_id == source_tender_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={'code': 'CONFLICT', 'message': 'Tender with this source_tender_id already exists'})
    tender = Tender(
        source_id=source_id,
        source_tender_id=source_tender_id,
        title=payload.title,
        description=payload.description,
        nmck=payload.nmck,
        currency=payload.currency,
        published_at=payload.published_at,
        deadline_at=payload.deadline_at,
        customer_name=payload.customer_name,
        customer_inn=payload.customer_inn,
        customer_kpp=payload.customer_kpp,
        platform=payload.platform,
        source_url=payload.source_url,
    )
    db.add(tender)
    await db.flush()
    for url in payload.documents_urls:
        db.add(TenderDocument(tender_id=tender.id, filename=url.split('/')[-1], source_url=url))
    await change_tender_status(db, tender, 'NEW', note='Тендер создан вручную')
    await db.commit()
    await db.refresh(tender)
    resp = {'success': True, 'data': {'id': tender.id, 'status': tender.status}}
    if not payload.skip_auto_processing:
        from app.workers.process_tender import process_tender
        task = Task(task_type='PROCESS_TENDER', status='PENDING', entity_type='tender', entity_id=tender.id)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        celery_task = process_tender.delay(str(tender.id), str(task.id))
        task.celery_task_id = celery_task.id
        await db.commit()
        resp['data']['task_id'] = task.id
    return resp

@router.get('/stats')
async def tender_stats(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(Tender)) or 0
    by_status = {}
    result = await db.execute(select(Tender.status, func.count()).group_by(Tender.status))
    for status, count in result.all():
        by_status[status] = count
    by_category = []
    cat_result = await db.execute(
        select(Tender.matched_category_id, Tender.category.has(), func.count())
        .group_by(Tender.matched_category_id, Tender.category.has())
    )
    for cat_id, has_cat, count in cat_result.all():
        if cat_id:
            category = await db.get(Category, cat_id)
            by_category.append({'category_id': cat_id, 'category_name': category.name if category else None, 'count': count})
    from datetime import timedelta
    processing_times = []
    history_result = await db.execute(
        select(TenderStatusHistory.tender_id, TenderStatusHistory.set_at)
        .where(TenderStatusHistory.status.in_(['READY_FOR_DECISION', 'APPROVED', 'REJECTED']))
    )
    ready_times = {}
    for t_id, ts in history_result.all():
        if t_id not in ready_times:
            ready_times[t_id] = ts
    if ready_times:
        tenders_result = await db.execute(select(Tender.id, Tender.created_at).where(Tender.id.in_(ready_times.keys())))
        for t_id, created_at in tenders_result.all():
            diff = (ready_times[t_id] - created_at).total_seconds() / 60
            if diff >= 0:
                processing_times.append(diff)
    avg_processing_time_minutes = round(sum(processing_times) / len(processing_times), 1) if processing_times else 0
    approved = await db.scalar(select(func.count()).select_from(Decision).where(Decision.decision == 'APPROVED')) or 0
    rejected = await db.scalar(select(func.count()).select_from(Decision).where(Decision.decision == 'REJECTED')) or 0
    total_decisions = approved + rejected
    approval_rate_percent = round(approved / total_decisions * 100, 1) if total_decisions else 0
    avg_margin_result = await db.execute(select(func.avg(Decision.margin_at_decision)).where(Decision.decision == 'APPROVED'))
    avg_margin = avg_margin_result.scalar()
    avg_margin_percent = float(avg_margin) if avg_margin else 0
    total_approved_volume = await db.scalar(
        select(func.sum(Tender.nmck)).join(Decision).where(Decision.decision == 'APPROVED')
    ) or 0
    return {
        'success': True,
        'data': {
            'total': total,
            'by_status': by_status,
            'by_category': by_category,
            'avg_processing_time_minutes': avg_processing_time_minutes,
            'approval_rate_percent': approval_rate_percent,
            'avg_margin_percent': avg_margin_percent,
            'total_approved_volume_rub': float(total_approved_volume),
        },
    }

@router.get('/{tender_id}')
async def get_tender(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tender = await db.get(
        Tender,
        tender_id,
        options=[
            selectinload(Tender.category),
            selectinload(Tender.source),
            selectinload(Tender.documents),
            selectinload(Tender.positions),
            selectinload(Tender.lot_suppliers).selectinload(LotSupplier.supplier),
            selectinload(Tender.lot_suppliers).selectinload(LotSupplier.commercial_offers),
            selectinload(Tender.status_history),
            selectinload(Tender.decisions),
        ],
    )
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    suppliers = []
    for ls in tender.lot_suppliers:
        offers = ls.commercial_offers
        margin = max((o.margin_percent for o in offers if o.margin_percent is not None), default=None)
        suppliers.append({
            'id': ls.id,
            'supplier_id': ls.supplier_id,
            'supplier_name': ls.supplier.name if ls.supplier else None,
            'status': ls.status,
            'has_cp': bool(offers),
            'cp_margin_percent': margin,
        })
    matched_categories = []
    if tender.matched_category_id:
        matched_categories.append({'id': tender.matched_category_id, 'name': tender.category.name if tender.category else None, 'similarity': tender.similarity_score})
    return {
        'success': True,
        'data': {
            'id': tender.id,
            'source': {'id': tender.source_id, 'name': tender.source.name if tender.source else None},
            'source_tender_id': tender.source_tender_id,
            'title': tender.title,
            'description': tender.description,
            'nmck': tender.nmck,
            'currency': tender.currency,
            'published_at': tender.published_at,
            'deadline_at': tender.deadline_at,
            'customer': {'name': tender.customer_name, 'inn': tender.customer_inn, 'kpp': tender.customer_kpp},
            'platform': tender.platform,
            'source_url': tender.source_url,
            'status': tender.status,
            'status_history': [{'status': h.status, 'set_at': h.set_at, 'note': h.note} for h in tender.status_history],
            'matched_categories': matched_categories,
            'score': tender.score,
            'score_components': tender.score_components,
            'structured_data': tender.structured_data,
            'positions': [
                {'id': p.id, 'position_number': p.position_number, 'name': p.name, 'characteristics': p.characteristics,
                 'gost': p.gost, 'okpd2': p.okpd2, 'quantity': p.quantity, 'unit': p.unit, 'is_essential': p.is_essential}
                for p in tender.positions
            ],
            'documents': [
                {'id': d.id, 'filename': d.filename, 'file_size_bytes': d.file_size_bytes, 'mime_type': d.mime_type,
                 'source_url': d.source_url, 'parse_status': d.parse_status, 'parsed_text_preview': (d.parsed_text or '')[:500]}
                for d in tender.documents
            ],
            'suppliers': suppliers,
            'created_at': tender.created_at,
            'updated_at': tender.updated_at,
        },
    }

@router.get('/{tender_id}/timeline')
async def get_timeline(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TenderStatusHistory).where(TenderStatusHistory.tender_id == tender_id).order_by(TenderStatusHistory.set_at.asc())
    )
    history = result.scalars().all()
    if not history:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    return {'success': True, 'data': [
        {'timestamp': h.set_at, 'event_type': 'STATUS_CHANGE', 'description': f"{h.previous_status or ''} -> {h.status}" + (f" ({h.note})" if h.note else ''), 'details': {}}
        for h in history
    ]}

@router.patch('/{tender_id}')
async def update_tender(tender_id: uuid.UUID, payload: TenderUpdate, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    old_status = tender.status
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tender, field, value)
    if payload.status:
        await change_tender_status(db, tender, payload.status, note='Статус обновлён вручную')
    await db.commit()
    await db.refresh(tender)
    if tender.status == 'READY_FOR_DECISION' and old_status != 'READY_FOR_DECISION':
        await notify_tender_ready_for_decision(tender.id)
    return {'success': True, 'data': {'id': tender.id, 'status': tender.status}}

@router.post('/{tender_id}/reprocess', status_code=202)
async def reprocess_tender(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from app.workers.process_tender import process_tender
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    existing_task = await db.execute(
        select(Task).where(
            Task.entity_type == 'tender',
            Task.entity_id == tender_id,
            Task.task_type == 'PROCESS_TENDER',
            Task.status.in_(['PENDING', 'IN_PROGRESS']),
        )
    )
    if existing_task.scalar_one_or_none():
        raise HTTPException(status_code=409, detail={'code': 'CONFLICT', 'message': 'Processing already in progress'})
    task = Task(task_type='PROCESS_TENDER', status='PENDING', entity_type='tender', entity_id=tender_id)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    celery_task = process_tender.delay(str(tender_id), str(task.id))
    task.celery_task_id = celery_task.id
    await db.commit()
    return {'success': True, 'data': {'task_id': task.id, 'status': 'ACCEPTED', 'check_url': f'/api/v1/tasks/{task.id}'}}

@router.post('/{tender_id}/supplier-search-results/confirm')
async def confirm_suppliers(tender_id: uuid.UUID, payload: SupplierConfirm, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    linked = 0
    for supplier_id in payload.supplier_ids:
        supplier = await db.get(Supplier, supplier_id)
        if not supplier:
            continue
        existing = await db.execute(select(LotSupplier).where(LotSupplier.tender_id == tender_id, LotSupplier.supplier_id == supplier_id))
        if existing.scalar_one_or_none():
            continue
        source = payload.source_by_id.get(str(supplier_id), 'internal_db')
        db.add(LotSupplier(tender_id=tender_id, supplier_id=supplier_id, source=source))
        linked += 1
    for item in payload.new_suppliers:
        name = item.get('name')
        email = item.get('email', '')
        if not name:
            continue
        existing_supplier = None
        if email:
            existing_supplier = (await db.execute(select(Supplier).where(Supplier.email == email))).scalar_one_or_none()
        if not existing_supplier and item.get('inn'):
            existing_supplier = (await db.execute(select(Supplier).where(Supplier.inn == item['inn']))).scalar_one_or_none()
        if existing_supplier:
            existing_ls = (await db.execute(select(LotSupplier).where(LotSupplier.tender_id == tender_id, LotSupplier.supplier_id == existing_supplier.id))).scalar_one_or_none()
            if not existing_ls:
                db.add(LotSupplier(tender_id=tender_id, supplier_id=existing_supplier.id, source='internal_db'))
                linked += 1
            continue
        supplier = Supplier(
            name=name, email=email, phone=item.get('phone', ''), website=item.get('website', ''),
            type=item.get('type', 'unknown'), tags=item.get('tags', [])
        )
        db.add(supplier)
        await db.flush()
        db.add(LotSupplier(tender_id=tender_id, supplier_id=supplier.id, source=item.get('source', 'google')))
        linked += 1
    await change_tender_status(db, tender, 'SUPPLIERS_FOUND', note=f'Привязано поставщиков: {linked}')
    await db.commit()
    return {'success': True, 'data': {'linked': linked}}

@router.post('/{tender_id}/request-cp', status_code=202)
async def request_cp(tender_id: uuid.UUID, payload: RequestCpPayload, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    from app.workers.send_communications import send_cp_requests
    task = Task(task_type='SEND_CP', status='PENDING', entity_type='tender', entity_id=tender_id, input_data={'supplier_ids': [str(s) for s in payload.supplier_ids]})
    db.add(task)
    await db.commit()
    await db.refresh(task)
    celery_task = send_cp_requests.delay(str(tender_id), str(task.id), [str(s) for s in payload.supplier_ids])
    task.celery_task_id = celery_task.id
    await db.commit()
    return {'success': True, 'data': {'task_id': task.id, 'status': 'ACCEPTED', 'check_url': f'/api/v1/tasks/{task.id}'}}

@router.post('/{tender_id}/search-suppliers', status_code=202)
async def search_suppliers(tender_id: uuid.UUID, payload: SearchSuppliersPayload, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    from app.workers.search_suppliers import search_suppliers_task
    task = Task(task_type='SEARCH_SUPPLIERS', status='PENDING', entity_type='tender', entity_id=tender_id, input_data=payload.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    celery_task = search_suppliers_task.delay(str(tender_id), str(task.id), payload.model_dump())
    task.celery_task_id = celery_task.id
    await db.commit()
    return {'success': True, 'data': {'task_id': task.id, 'status': 'ACCEPTED', 'check_url': f'/api/v1/tasks/{task.id}'}}

@router.get('/{tender_id}/supplier-search-results')
async def supplier_search_results(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    result = await db.execute(
        select(Task).where(
            Task.entity_type == 'tender',
            Task.entity_id == tender_id,
            Task.task_type == 'SEARCH_SUPPLIERS',
            Task.status == 'COMPLETED',
        ).order_by(Task.completed_at.desc()).limit(1)
    )
    task = result.scalar_one_or_none()
    if not task or not task.output_data:
        return {'success': True, 'data': {'tender_id': tender_id, 'status': 'NOT_SEARCHED', 'searched_at': None, 'search_queries_used': [], 'total_found': 0, 'after_dedup': 0, 'after_priority_filter': 0, 'suppliers': []}}
    return {
        'success': True,
        'data': {
            'tender_id': tender_id,
            'status': 'SUPPLIERS_FOUND',
            'searched_at': task.completed_at,
            'search_queries_used': task.output_data.get('queries', []),
            'total_found': len(task.output_data.get('results', [])),
            'after_dedup': len(task.output_data.get('results', [])),
            'after_priority_filter': len(task.output_data.get('results', [])),
            'suppliers': task.output_data.get('results', []),
        },
    }

@router.get('/{tender_id}/communications')
async def tender_communications(tender_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    comms = (await db.execute(
        select(Communication).where(Communication.tender_id == tender_id).order_by(Communication.created_at.asc())
    )).scalars().all()
    grouped = {}
    for c in comms:
        grouped.setdefault(c.lot_supplier_id, []).append(c)
    lot_suppliers = (await db.execute(
        select(LotSupplier).where(LotSupplier.tender_id == tender_id).options(
            selectinload(LotSupplier.supplier),
            selectinload(LotSupplier.commercial_offers),
        )
    )).scalars().all()
    threads = []
    for ls in lot_suppliers:
        messages = grouped.get(ls.id, [])
        cp = ls.commercial_offers[0] if ls.commercial_offers else None
        threads.append({
            'lot_supplier_id': ls.id,
            'supplier_id': ls.supplier_id,
            'supplier_name': ls.supplier.name if ls.supplier else None,
            'status': ls.status,
            'last_contact_at': messages[-1].sent_at or messages[-1].received_at if messages else None,
            'has_cp': bool(cp),
            'cp_id': cp.id if cp else None,
            'cp_status': cp.status if cp else None,
            'messages': [
                {
                    'id': c.id, 'direction': c.direction, 'channel': c.channel, 'subject': c.subject,
                    'body_text': c.body_text, 'message_type': c.message_type,
                    'attachments': [], 'sent_at': c.sent_at, 'received_at': c.received_at,
                }
                for c in messages
            ],
        })
    return {'success': True, 'data': {'tender_id': tender_id, 'supplier_threads': threads}}

@router.post('/{tender_id}/communications/send', status_code=201)
async def send_communication(tender_id: uuid.UUID, payload: CommunicationSendPayload, db: AsyncSession = Depends(get_db)):
    tender = await db.get(Tender, tender_id)
    if not tender:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'Tender not found'})
    ls = (await db.execute(select(LotSupplier).where(LotSupplier.tender_id == tender_id, LotSupplier.supplier_id == payload.supplier_id))).scalar_one_or_none()
    if not ls:
        raise HTTPException(status_code=404, detail={'code': 'NOT_FOUND', 'message': 'LotSupplier not found'})
    comm = Communication(
        lot_supplier_id=ls.id,
        tender_id=tender_id,
        direction='outgoing',
        channel=payload.channel,
        subject=payload.subject,
        body_text=payload.body,
        message_type=payload.message_type,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(comm)
    await db.commit()
    await db.refresh(comm)
    return {'success': True, 'data': {'id': comm.id}}