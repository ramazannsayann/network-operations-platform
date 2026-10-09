# Developer shortcuts. Run `make` (or `make help`) to list targets.

COMPOSE := docker compose -f deploy/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help install env up down logs ps migrate test test-integration test-scale lint format openapi mock

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# A new Fernet key: 32 random bytes, URL-safe base64.
NEW_FERNET_KEY = $$(openssl rand -base64 32 | tr '+/' '-_')

# Created on first use from the example, with a random database password and a random
# credentials key; `env` adds the key to files created before it existed.
deploy/.env:
	@sed -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$(openssl rand -hex 24)/" \
	     -e "s/^CREDENTIALS_KEY=.*/CREDENTIALS_KEY=$(NEW_FERNET_KEY)/" deploy/.env.example > $@
	@echo "Created $@ with a random POSTGRES_PASSWORD and CREDENTIALS_KEY."

env: deploy/.env
	@grep -q '^CREDENTIALS_KEY=' deploy/.env || { \
	  echo "CREDENTIALS_KEY=$(NEW_FERNET_KEY)" >> deploy/.env; \
	  echo "Added a random CREDENTIALS_KEY to deploy/.env; back it up (see ADR-0004)."; }

install: ## Install backend + frontend dependencies and the git pre-commit hooks
	cd backend && uv sync
	cd frontend && npm ci
	uv run --project backend pre-commit install

up: env ## Build and start the whole stack in the background
	$(COMPOSE) up --build --detach

down: ## Stop the stack (the database volume is kept)
	$(COMPOSE) down

logs: ## Follow the logs of all services
	$(COMPOSE) logs --follow --tail=100

ps: ## Show service status and health
	$(COMPOSE) ps

migrate: env ## Apply database migrations (alembic upgrade head); `make up` also does this
	$(COMPOSE) run --rm migrate

test: ## Run the backend unit tests (no database or network needed)
	cd backend && uv run pytest

# Credentials come from deploy/.env; the tests create their own netops_test database.
TEST_DB_ENV = set -a && . ./deploy/.env && set +a && cd backend && \
	TEST_POSTGRES_PORT="$${DB_HOST_PORT:-5433}" TEST_POSTGRES_USER="$$POSTGRES_USER" \
	TEST_POSTGRES_PASSWORD="$$POSTGRES_PASSWORD"

test-integration: env ## Run integration tests against the compose db (needs `make up`)
	$(TEST_DB_ENV) uv run pytest -m "integration and not scale"

SCALE_DEVICES ?= 50
test-scale: env ## Discover a generated campus of SCALE_DEVICES (default 50) and time it
	$(TEST_DB_ENV) SCALE_DEVICES=$(SCALE_DEVICES) uv run pytest -m scale

openapi: ## Regenerate docs/api/openapi.json and the frontend's TypeScript types from the code
	cd backend && uv run python -m netops.api.export_openapi ../docs/api/openapi.json
	cd frontend && npm run gen:api

mock: ## Serve the API contract with example data (Prism) on http://127.0.0.1:4010
	cd frontend && npm run mock

lint: ## Lint, format-check and type-check backend and frontend
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd frontend && npm run lint && npm run format:check && npm run typecheck

format: ## Auto-fix lint issues and format all code
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format
