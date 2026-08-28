import asyncio
import structlog
from typing import Any
from app.core.config import settings

logger = structlog.get_logger(__name__)

async def chat_completion(prompt: str, system: str = "") -> str:
    """Универсальный вызов LLM с ретраями (3 попытки, экспоненциальная задержка)."""
    if not settings.llm_api_key:
        return ""
    max_retries = 3
    delay = 1
    for attempt in range(1, max_retries + 1):
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_api_base)
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = await client.chat.completions.create(
                model=settings.llm_model_chat,
                messages=messages,
                temperature=0.2,
                timeout=30,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning("llm.retry", attempt=attempt, error=str(e))
            if attempt == max_retries:
                logger.error("llm.failed", error=str(e))
                return ""
            await asyncio.sleep(delay)
            delay *= 2
    return ""