from datetime import datetime

from app.workers.celery_app import celery_app


@celery_app.task(name="import_categories")
def import_categories_task(categories: list[dict], task_id: str | None = None) -> dict:
    import asyncio
    from uuid import UUID

    from app.core.database import AsyncSessionLocal
    from app.models import Category, Task
    from app.services.embedding_service import get_embedding_or_empty

    async def _import():
        async with AsyncSessionLocal() as db:
            task = await db.get(Task, UUID(task_id)) if task_id else None
            if task:
                task.status = "IN_PROGRESS"
                await db.commit()

            created = 0
            for item in categories:
                category = Category(
                    name=item["name"],
                    description=item["description"],
                    keywords=item.get("keywords", []),
                    parent_id=item.get("parent_id"),
                )
                text = f"{category.name} {category.description} {' '.join(category.keywords)}"
                category.embedding = await get_embedding_or_empty(text)
                db.add(category)
                created += 1

            await db.commit()

            if task:
                task = await db.get(Task, UUID(task_id))
                if task:
                    task.status = "COMPLETED"
                    task.output_data = {"created": created}
                    task.completed_at = datetime.utcnow()
                    await db.commit()
            return created

    asyncio.run(_import())
    return {"created": len(categories)}
