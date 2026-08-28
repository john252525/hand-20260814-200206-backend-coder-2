#!/bin/bash
set -e

echo "Очистка дублирующихся каталогов и временных файлов..."

# Удаляем backend/backend (вся копия)
rm -rf backend/backend

# Удаляем вложенные дубли миграций
rm -rf backend/migrations/migrations

# Удаляем корневые каталоги migrations
rm -rf migrations

# Удаляем временные файлы
rm -f embedding_service_fixed.py process_tender_fixed.py sync_tenders_fixed.py

# Удаляем __pycache__ и .pyc
find . -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find . -type f -name '*.pyc' -delete

# Удаляем пустые директории
find . -type d -empty -delete 2>/dev/null || true

echo "Готово. Проверьте структуру:"
echo "find . -type f | sort | head -50"