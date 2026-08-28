# Tender Pipeline Backend

Автоматизированный конвейер обработки тендеров.

## Стек
FastAPI + PostgreSQL/pgvector + Redis + Celery + OpenAI + Google Search + SMTP/IMAP

## Быстрый старт

1. `cp .env.example .env`
2. `docker-compose up -d postgres redis`
3. `cd backend && make migrate`
4. `make run`, `make worker`, `make beat`

## Очистка репозитория
Если в репозитории остались дублирующиеся каталоги (`backend/backend/`, корневые `migrations/`) или временные файлы (`*_fixed.py`), выполните:
```bash
./cleanup.sh
```

## Демо-сценарий
1. Создать токен: `python -m app.cli.token_cli create --description "demo"`
2. Создать источник: `POST /api/v1/tender-sources`
3. Синхронизация: `POST /api/v1/tender-sources/{id}/sync`
4. Обработка: `POST /api/v1/tenders/{id}/reprocess`
5. Поиск и подтверждение поставщиков
6. Запрос КП: `POST /api/v1/tenders/{id}/request-cp`
7. Получение ответов через IMAP (автоматически)
8. КП в `/api/v1/commercial-offers`
9. Переговоры: `POST /api/v1/negotiations/tenders/{id}/negotiate`
10. Решение: `POST /api/v1/decisions/{tender_id}/approve` или `/reject`
11. Файлы: `POST /api/v1/files/upload`, `GET /api/v1/files/{id}/download`, `DELETE /api/v1/files/{id}`

## Тесты
```bash
cd backend
pytest -v
```