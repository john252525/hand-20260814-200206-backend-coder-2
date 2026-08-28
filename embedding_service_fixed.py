# Исправленный embedding_service.py с fallback-сигналом
from typing import List, Tuple

from app.core.config import settings


async def generate_embedding(text: str) -> Tuple[List[float], bool]:
    """Возвращает (эмбеддинг, is_degraded).
    Если API недоступен — нулевой вектор и is_degraded=True.
    """
    if not settings.llm_api_key:
        return [0.0] * settings.llm_embedding_dimensions, True
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_api_base)
        resp = await client.embeddings.create(
            model=settings.llm_model_embedding,
            input=text,
        )
        return resp.data[0].embedding, False
    except Exception:
        return [0.0] * settings.llm_embedding_dimensions, True


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
