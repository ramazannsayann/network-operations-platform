# Developer shortcuts. Run `make` (or `make help`) to list targets.

COMPOSE := docker compose -f deploy/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help install up down logs ps migrate test lint format

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Created on first use from the example, with a random database password.
deploy/.env:
	@sed "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$(openssl rand -hex 24)/" deploy/.env.example > $@
	@echo "Created $@ with a random POSTGRES_PASSWORD."

install: ## Install backend + frontend dependencies and the git pre-commit hooks
	cd backend && uv sync
	cd frontend && npm ci
	uv run --project backend pre-commit install

up: deploy/.env ## Build and start the whole stack in the background
	$(COMPOSE) up --build --detach

down: ## Stop the stack (the database volume is kept)
	$(COMPOSE) down

logs: ## Follow the logs of all services
	$(COMPOSE) logs --follow --tail=100

ps: ## Show service status and health
	$(COMPOSE) ps

migrate: deploy/.env ## Apply database migrations (alembic upgrade head)
	$(COMPOSE) run --rm api alembic upgrade head

test: ## Run the backend test suite
	cd backend && uv run pytest

lint: ## Lint, format-check and type-check backend and frontend
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd frontend && npm run lint && npm run format:check && npm run typecheck

format: ## Auto-fix lint issues and format all code
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && npm run format
