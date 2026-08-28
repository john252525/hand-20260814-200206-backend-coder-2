.PHONY: run worker beat migrate makemigrations test test_all lint clean

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

beat:
	celery -A app.workers.celery_app beat --loglevel=info

migrate:
	alembic upgrade head

makemigrations:
	alembic revision --autogenerate -m "$(m)"

test:
	pytest -v

test_all:
	python -m pytest tests/ -v

lint:
	ruff check app

clean:
	../cleanup.sh