# Tender Pipeline Backend

Автоматизированный конвейер обработки тендеров.

## Стек
FastAPI + PostgreSQL/pgvector + Redis + Celery + OpenAI + Google Search + SMTP/IMAP

## Статус готовности
- **Функциональность по ТЗ: ~95%** (с учётом осознанных упрощений).
- Критические блокеры устранены: синхронизация с ГосПлан API (пагинация, API-ключ, защита от ложной архивации), регистрация Celery-задач, health-check источников тендеров, передача параметров синхронизации.
- Реализованы: полная синхронизация с курсорной пагинацией, восстановление тендеров из архива, тест соединения с источником.
- Осталось для продакшена: загрузка реальных документов (PDF/DOCX), расширенная статистика поставщиков, интеграция ML-модели в скоринг.

## Быстрый старт
1. `cp .env.example .env`
2. Настройте переменные окружения (БД, Redis, LLM, Google, SMTP/IMAP, ГосПлан).
3. `docker-compose up -d postgres redis`
4. `cd backend && make migrate`
5. `make run`, `make worker`, `make beat`
6. При необходимости выполните очистку репозитория: `./cleanup.sh`

## Демо-сценарий
1. **Создать API-токен**
   ```bash
   python -m app.cli.token_cli create --description "demo"
   ```
   Используйте полученный токен в заголовке `X-API-Token`.

2. **Создать источник тендеров**
   ```http
   POST /api/v1/tender-sources
   {
     "name": "ГосПлан",
     "type": "aggregator_api",
     "api_url": "https://v2test.gosplan.info/fz44/purchases",
     "config": {"page_size": 50}
   }
   ```

3. **Проверить соединение с источником**
   ```http
   POST /api/v1/tender-sources/{source_id}/test-connection
   ```
   Ответ содержит `reachable`, `latency_ms`, `tenders_available`.

4. **Запустить синхронизацию**
   ```http
   POST /api/v1/tender-sources/{source_id}/sync
   {
     "since": null,
     "full_resync": false
   }
   ```
   Можно указать `since` (например, `"2026-08-01T00:00:00Z"`) или `full_resync: true` для полной пересинхронизации.
   Получите `task_id`, статус проверяйте через `GET /api/v1/tasks/{task_id}`.

5. **Обработка тендеров**
   После синхронизации тендеры имеют статус `NEW`. Для запуска конвейера:
   ```http
   POST /api/v1/tenders/{tender_id}/reprocess
   ```
   Конвейер: документы → извлечение текста → категоризация → скоринг → статус `AWAITING_SUPPLIER_SEARCH`.

6. **Поиск поставщиков**
   ```http
   POST /api/v1/tenders/{tender_id}/search-suppliers
   {
     "max_suppliers": 10,
     "channels": ["google", "internal_db"]
   }
   ```
   Результаты поиска: `GET /api/v1/tenders/{tender_id}/supplier-search-results`.
   Подтвердите выбранных: `POST /api/v1/tenders/{tender_id}/supplier-search-results/confirm`.

7. **Запрос КП**
   ```http
   POST /api/v1/tenders/{tender_id}/request-cp
   {
     "supplier_ids": ["uuid1", "uuid2"]
   }
   ```
   Если SMTP не настроен, письма сохраняются в БД с пометкой. Настройте IMAP для автоматической обработки входящих.

8. **Получение ответов**
   Входящие письма обрабатываются автоматически (Celery Beat каждые 5 минут).
   КП сохраняются в `/api/v1/commercial-offers`.

9. **Переговоры**
   ```http
   POST /api/v1/tenders/{tender_id}/negotiate
   {
     "action": "request_clarification",
     "target_supplier_ids": ["uuid"]
   }
   ```
   Статус: `GET /api/v1/tenders/{tender_id}/negotiation-status`.

10. **Решение**
    ```http
    POST /api/v1/decisions/{tender_id}/approve
    {
      "chosen_supplier_id": "uuid",
      "chosen_offer_id": "uuid",
      "comment": "Отличная маржа"
    }
    ```
    или
    ```http
    POST /api/v1/decisions/{tender_id}/reject
    {
      "reason": "low_margin",
      "comment": "Маржа ниже 20%"
    }
    ```

11. **Файлы**
    Загрузка: `POST /api/v1/files/upload` (multipart/form-data с полями `file`, `entity_type`, `entity_id`).
    Скачивание: `GET /api/v1/files/{file_id}/download`.

## Тесты
```bash
cd backend
pytest -v
```

## Примечания
- Для продакшена обязательно используйте HTTPS и реальные ключи API.
- Валидация данных на входе выполнена (например, формат `since`).
- Рекомендуется запустить `./cleanup.sh` перед деплоем для удаления дубликатов и временных файлов.
