.PHONY: format lint test migrate docker-config

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
