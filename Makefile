.PHONY: format lint test migrate docker-config uv_sync dc.db local health upload query_rag dc.clear_s3 dc.drop_db

format:
	uv run ruff format .

lint:
	uv run ruff check .

test:
	uv run pytest

migrate:
	uv run alembic upgrade head

docker-config:
	docker compose config --quiet

uv_sync:
	uv sync --extra rag

dc.db:
	docker compose up --build -d postgres minio create-buckets

local:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8080

worker:
	uv run python -m worker.ingest_worker

wiki:
	uv run python wiki

health:
	curl http://127.0.0.1:8080/health | python3 -m json.tool

upload:
	sh ./upload_sample_docs.sh

dc.check_upload:
	docker compose exec postgres psql -U rag -d rag -c \
	"select tenant_id, source_id, status, error, updated_at from ingest_job order by updated_at desc;"

dc.check_worker_logs:
	docker compose logs -f worker

query_rag:
	sh query_rag.sh

dc.clear_s3:
	docker compose run --rm --entrypoint /bin/sh create-buckets -ec 'mc alias set local http://minio:9000 "$$MINIO_ROOT_USER" "$$MINIO_ROOT_PASSWORD"; mc rm --recursive --force "local/$$S3_BUCKET_RAW" || true; mc rm --recursive --force "local/$$S3_BUCKET_ASSETS" || true; mc mb --ignore-existing "local/$$S3_BUCKET_RAW"; mc mb --ignore-existing "local/$$S3_BUCKET_ASSETS"'

dc.drop_db:
	docker-compose exec postgres psql -U rag -d postgres -c "DROP DATABASE IF EXISTS rag;" -c "CREATE DATABASE rag;"
