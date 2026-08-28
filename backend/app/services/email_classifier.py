from typing import Tuple

from app.services.llm_service import chat_completion


CLASSIFIER_PROMPT = """
Классифицируй входящее письмо по его содержанию.
Тема: {subject}
Текст: {body}
Классификация:
- cp_response: содержит коммерческое предложение, цены, сроки (есть вложение или цены в тексте)
- decline: отказ от участия ("не работаем", "не поставляем", "не наш профиль")
- question: уточняющие вопросы по закупке
- auto_reply: автоответ ("получили", "обрабатывается", "на рассмотрении")
- out_of_office: офис отсутствует, в отпуске
- spam: спам, реклама
- other: не подходит ни под одну категорию
Ответ — ТОЛЬКО одно слово из списка выше.
"""


async def classify_email(subject: str, body: str) -> str:
    """Возвращает одно из: cp_response, decline, question, auto_reply, out_of_office, spam, other."""
    result = await chat_completion(CLASSIFIER_PROMPT.format(subject=subject, body=body[:2000]))
    if result:
        result = result.strip().lower()
        allowed = {"cp_response", "decline", "question", "auto_reply", "out_of_office", "spam", "other"}
        if result in allowed:
            return result

    # Fallback на ключевые слова
    text = (subject + " " + body).lower()
    if any(word in text for word in ["коммерческое предложение", "кп", "счет", "цена", "price"]):
        return "cp_response"
    if any(word in text for word in ["отказ", "не работаем", "не поставляем", "decline"]):
        return "decline"
    if any(word in text for word in ["получили", "обрабатывается", "на рассмотрении", "auto-reply", "автоответ"]):
        return "auto_reply"
    if any(word in text for word in ["в отпуске", "out of office", "отпуск"]):
        return "out_of_office"
    return "other"
