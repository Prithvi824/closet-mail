# Common developer commands. Run from the repo root.
COMPOSE_DEV := docker compose -f deploy/docker-compose.dev.yml

.PHONY: test lint typecheck dev-up dev-down migrate api-types

test:
	cd backend && uv run pytest
	cd edge && npm test
	@if [ -d web ]; then cd web && npm test; fi
	cd landing && npm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	@if [ -d web ]; then cd web && npm run lint; fi
	cd landing && npm run lint

typecheck:
	cd backend && uv run mypy mailalias
	cd edge && npx tsc --noEmit
	@if [ -d web ]; then cd web && npx tsc --noEmit; fi
	cd landing && npx astro check

dev-up:
	$(COMPOSE_DEV) up -d --wait

dev-down:
	$(COMPOSE_DEV) down

migrate:
	cd backend && uv run alembic upgrade head

# Regenerate web/src/lib/api-types.ts from the backend's OpenAPI schema (no server needed).
api-types:
	cd backend && APP_ENV=test uv run python -c "import json; from mailalias.api.app import create_app; print(json.dumps(create_app().openapi()))" > ../web/openapi.json
	cd web && npx openapi-typescript openapi.json --default-non-nullable false -o src/lib/api-types.ts && rm openapi.json
