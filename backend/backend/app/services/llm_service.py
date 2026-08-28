from typing import Any

from app.core.config import settings


async def chat_completion(prompt: str, system: str = "") -> str:
    """Универсальный вызов LLM с fallback."""
    if not settings.llm_api_key:
        return ""
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
        )
        return resp.choices[0].message.content or ""
    except Exception:
        return ""
