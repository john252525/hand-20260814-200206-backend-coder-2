from app.services.webhook_dispatcher import send_webhook_event


async def notify_tender_ready_for_decision(tender_id):
    # Передаём db=None, чтобы создать отдельную сессию и избежать двойного commit
    await send_webhook_event("tender.ready_for_decision", {"tender_id": str(tender_id)})


async def notify_cp_received(commercial_offer_id, tender_id):
    await send_webhook_event("cp.received", {"offer_id": str(commercial_offer_id), "tender_id": str(tender_id)})


async def notify_task_completed(task_id):
    await send_webhook_event("task.completed", {"task_id": str(task_id)})


async def notify_decision_made(tender_id, decision):
    await send_webhook_event("decision.made", {"tender_id": str(tender_id), "decision": decision})
