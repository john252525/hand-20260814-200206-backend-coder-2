import structlog
from app.services.webhook_dispatcher import send_webhook_event
logger = structlog.get_logger(__name__)

async def notify_tender_ready_for_decision(tender_id):
    logger.info('webhook.notify', event='tender.ready_for_decision', tender_id=str(tender_id))
    await send_webhook_event('tender.ready_for_decision', {'tender_id': str(tender_id)})

async def notify_cp_received(commercial_offer_id, tender_id):
    logger.info('webhook.notify', event='cp.received', offer_id=str(commercial_offer_id), tender_id=str(tender_id))
    await send_webhook_event('cp.received', {'offer_id': str(commercial_offer_id), 'tender_id': str(tender_id)})

async def notify_task_completed(task_id):
    logger.info('webhook.notify', event='task.completed', task_id=str(task_id))
    await send_webhook_event('task.completed', {'task_id': str(task_id)})

async def notify_decision_made(tender_id, decision):
    logger.info('webhook.notify', event='decision.made', tender_id=str(tender_id), decision=decision)
    await send_webhook_event('decision.made', {'tender_id': str(tender_id), 'decision': decision})

async def notify_supplier_created(supplier_id):
    logger.info('webhook.notify', event='supplier.created', supplier_id=str(supplier_id))
    await send_webhook_event('supplier.created', {'supplier_id': str(supplier_id)})

async def notify_negotiation_step(tender_id, supplier_id, action):
    logger.info('webhook.notify', event='negotiation.step', tender_id=str(tender_id), supplier_id=str(supplier_id), action=action)
    await send_webhook_event('negotiation.step', {'tender_id': str(tender_id), 'supplier_id': str(supplier_id), 'action': action})
