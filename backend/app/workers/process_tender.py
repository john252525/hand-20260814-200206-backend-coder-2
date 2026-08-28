import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import AsyncSessionLocal
from app.models import Category, Tender, TenderRequirement, Task
from app.services.embedding_service import cosine_similarity, generate_embedding
from app.services.scoring_service import calculate_score
from app.services.tender_status_service import change_tender_status
from app.services.document_parser import extract_tender_data
from app.services.settings_service import get_section
from app.workers.celery_app import celery_app

@celery_app.task(name="process_tender", bind=True)
def process_tender(self, tender_id: str, task_id: str | None = None) -> dict:
    try:
        asyncio.run(_process(tender_id, task_id))
        return {"status": "processed"}
    except Exception as e:
        if task_id:
            asyncio.run(_update_task_error(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)

async def _update_task_error(task_id: str, error: str):
    from uuid import UUID
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, UUID(task_id))
        if task:
            task.status = "FAILED"
            task.error_message = error
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

async def _process(tender_id: str, task_id: str | None = None):
    from uuid import UUID
    if task_id:
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "IN_PROGRESS"
                await db.commit()
    async with AsyncSessionLocal() as db:
        tender = await db.get(
            Tender,
            UUID(tender_id),
            options=[selectinload(Tender.documents), selectinload(Tender.positions)],
        )
        if not tender:
            return
        await change_tender_status(db, tender, "DOCUMENTS_LOADING", note="Начало обработки")
        await change_tender_status(db, tender, "DOCUMENTS_LOADED", note="Документы загружены (демо)")
        await change_tender_status(db, tender, "PROCESSING", note="Извлечение текста")
        await extract_tender_data(db, tender)
        await db.flush()
        await change_tender_status(db, tender, "SEMANTIC_FILTERING")
        docs_text = "\n".join(d.parsed_text for d in tender.documents if d.parsed_text)
        text_portrait = f"{tender.title} {tender.description} {docs_text}".strip()[:8000]
        embedding = await generate_embedding(text_portrait)
        tender.embedding = embedding
        result = await db.execute(select(Category).where(Category.is_active == True))
        categories = result.scalars().all()
        best_sim = 0.0
        best_cat = None
        for cat in categories:
            if cat.embedding and any(x != 0 for x in cat.embedding):
                sim = cosine_similarity(embedding, cat.embedding)
                if sim > best_sim:
                    best_sim = sim
                    best_cat = cat
            else:
                cat_words = set((cat.name + " " + " ".join(cat.keywords)).lower().split())
                text_words = set(text_portrait.lower().split())
                common = len(cat_words.intersection(text_words))
                if common >= 2 and common / max(len(cat_words), 1) > 0.3:
                    fallback_sim = 0.65
                    if fallback_sim > best_sim:
                        best_sim = fallback_sim
                        best_cat = cat
        filters = await get_section(db, "filters")
        accept_threshold = filters.get("min_similarity_accept", 0.75)
        uncertain_threshold = filters.get("min_similarity_uncertain", 0.60)
        if best_cat and best_sim >= accept_threshold:
            tender.matched_category_id = best_cat.id
            tender.similarity_score = best_sim
            await change_tender_status(db, tender, "RELEVANT", note=f"Сходство {best_sim:.2f} с категорией {best_cat.name}")
        elif best_cat and best_sim >= uncertain_threshold:
            tender.matched_category_id = best_cat.id
            tender.similarity_score = best_sim
            await change_tender_status(db, tender, "UNCERTAIN", note=f"Пограничное сходство {best_sim:.2f} с категорией {best_cat.name}")
            await db.commit()
            if task_id:
                task = await db.get(Task, UUID(task_id))
                if task:
                    task.status = "COMPLETED"
                    task.output_data = {"status": "UNCERTAIN", "similarity": best_sim}
                    task.completed_at = datetime.now(timezone.utc)
                    await db.commit()
            return
        else:
            await change_tender_status(db, tender, "NOT_RELEVANT", note="Не соответствует категориям")
            await db.commit()
            if task_id:
                task = await db.get(Task, UUID(task_id))
                if task:
                    task.status = "COMPLETED"
                    task.output_data = {"status": "NOT_RELEVANT"}
                    task.completed_at = datetime.now(timezone.utc)
                    await db.commit()
            return
        await change_tender_status(db, tender, "SCORING")
        scoring_settings = await get_section(db, "scoring")
        company_settings = await get_section(db, "company")
        req_result = await db.execute(select(TenderRequirement).where(TenderRequirement.tender_id == tender.id))
        requirements = req_result.scalar_one_or_none()
        score, components = await calculate_score(
            tender, scoring_settings, requirements, db=db, company_settings=company_settings
        )
        tender.score = score
        tender.score_components = components
        await change_tender_status(db, tender, "SCORED", note=f"Скор: {score}")
        await change_tender_status(db, tender, "AWAITING_SUPPLIER_SEARCH", note="Ожидание поиска поставщиков")
        await db.commit()
        if task_id:
            task = await db.get(Task, UUID(task_id))
            if task:
                task.status = "COMPLETED"
                task.output_data = {"status": "AWAITING_SUPPLIER_SEARCH", "score": score}
                task.completed_at = datetime.now(timezone.utc)
                await db.commit()