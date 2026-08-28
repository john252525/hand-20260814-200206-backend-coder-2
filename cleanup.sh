#!/bin/bash
set -e

echo "Очистка дублирующихся каталогов и временных файлов..."
rm -rf backend/backend
rm -rf migrations
rm -f embedding_service_fixed.py process_tender_fixed.py sync_tenders_fixed.py

echo "Готово. Осталось только backend/ и корневые файлы."