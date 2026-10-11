# Developer shortcuts. Run `make` (or `make help`) to list targets.

COMPOSE := docker compose -f deploy/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help install env up down logs ps migrate test test-integration test-scale lint format openapi mock \
	fakelab-compose fakelab-up fakelab-seed fakelab-discover fakelab-accuracy fakelab-down \
	fakelab-change fakelab-reset fakelab-backup fakelab-fixtures fakelab-users fakelab-mfa-reset

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# A new Fernet key: 32 random bytes, URL-safe base64.
NEW_FERNET_KEY = $$(openssl rand -base64 32 | tr '+/' '-_')
NEW_SIGNING_KEY = $$(openssl rand -hex 32)

# Created on first use from the example, with a random database password and a random
# credentials key; `env` adds the key to files created before it existed.
deploy/.env:
	@sed -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$(openssl rand -hex 24)/" \
	     -e "s/^CREDENTIALS_KEY=.*/CREDENTIALS_KEY=$(NEW_FERNET_KEY)/" \
	     -e "s/^AUTH_SIGNING_KEY=.*/AUTH_SIGNING_KEY=$(NEW_SIGNING_KEY)/" deploy/.env.example > $@
	@echo "Created $@ with a random POSTGRES_PASSWORD, CREDENTIALS_KEY and AUTH_SIGNING_KEY."

env: deploy/.env
	@grep -q '^CREDENTIALS_KEY=' deploy/.env || { \
	  echo "CREDENTIALS_KEY=$(NEW_FERNET_KEY)" >> deploy/.env; \
	  echo "Added a random CREDENTIALS_KEY to deploy/.env; back it up (see ADR-0004)."; }
	@grep -Eq '^AUTH_SIGNING_KEY=.{32,}$$' deploy/.env || { \
	  sed -i.bak '/^AUTH_SIGNING_KEY=/d' deploy/.env && rm -f deploy/.env.bak; \
	  echo "AUTH_SIGNING_KEY=$(NEW_SIGNING_KEY)" >> deploy/.env; \
	  echo "Added a random AUTH_SIGNING_KEY to deploy/.env (signs access tokens, ADR-0008)."; }

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

# --- Fake lab (lab/fakelab/topology.yaml): fake Cisco devices in containers ---------------------

COMPOSE_FAKELAB := $(COMPOSE) -f deploy/docker-compose.fakelab.yml --profile fakelab
FAKELAB_SEED := 10.255.0.2
FAKELAB_SUBNET := 10.255.0.0/24

fakelab-compose: ## Regenerate deploy/docker-compose.fakelab.yml from the topology file
	cd backend && uv run python -m netops_fakes.compose ../lab/fakelab/topology.yaml \
	  > ../deploy/docker-compose.fakelab.yml

fakelab-fixtures: ## Regenerate the running-config fixtures (lab/fixtures) from the fake lab
	cd backend && uv run python -m netops_fakes.fixtures ../lab/fakelab/topology.yaml \
	  ../lab/fixtures/cisco_ios/show_running-config

fakelab-up: env ## Start the stack plus the fake lab's devices (worker joins 10.255.0.0/24)
	@grep -q '^FAKELAB_PASSWORD=' deploy/.env || { \
	  echo "FAKELAB_PASSWORD=$$(openssl rand -hex 16)" >> deploy/.env; \
	  echo "Added a random FAKELAB_PASSWORD to deploy/.env."; }
	$(COMPOSE_FAKELAB) up --build --detach --wait

# UI users of the fake lab, one per role, all with FAKELAB_UI_PASSWORD (random, in
# deploy/.env). Admins and operators set up MFA at their first sign-in.
fakelab-users: ## Create the UI users fakelab-admin, fakelab-operator, fakelab-viewer
	@grep -q '^FAKELAB_UI_PASSWORD=' deploy/.env || { \
	  echo "FAKELAB_UI_PASSWORD=ui-$$(openssl rand -hex 12)" >> deploy/.env; \
	  echo "Added a random FAKELAB_UI_PASSWORD to deploy/.env."; }
	@set -a && . ./deploy/.env && set +a && \
	for user in fakelab-admin:admin fakelab-operator:operator fakelab-viewer:viewer; do \
	  name=$${user%%:*}; role=$${user##*:}; \
	  printf '%s\n' "$$FAKELAB_UI_PASSWORD" | $(COMPOSE_FAKELAB) exec -T api netops users create \
	    $$name --role $$role --no-temporary --password-stdin 2>/dev/null || \
	  printf '%s\n' "$$FAKELAB_UI_PASSWORD" | $(COMPOSE_FAKELAB) exec -T api netops users \
	    set-password $$name --no-temporary --password-stdin; \
	done

USERNAME ?= fakelab-admin
fakelab-mfa-reset: ## Remove a fake lab UI user's MFA (USERNAME=fakelab-admin); enrolls again
	$(COMPOSE_FAKELAB) exec -T api netops users reset-mfa $(USERNAME)

# Two profiles: an outdated one (random password no device accepts) and the lab's, so
# discovery shows the two-attempt login and remembers the profile that worked.
fakelab-seed: ## Create the fake lab's credential profiles (netops credentials add)
	@set -a && . ./deploy/.env && set +a && \
	openssl rand -hex 16 | $(COMPOSE_FAKELAB) exec -T api netops credentials add \
	  fakelab-outdated --username "$${FAKELAB_USERNAME:-netops-ro}" --password-stdin --update && \
	printf '%s\n' "$$FAKELAB_PASSWORD" | $(COMPOSE_FAKELAB) exec -T api netops credentials add \
	  fakelab --username "$${FAKELAB_USERNAME:-netops-ro}" --password-stdin --update

fakelab-discover: ## Discover the fake lab from core1 and wait for the result
	$(COMPOSE_FAKELAB) exec -T api netops discover --seed $(FAKELAB_SEED) \
	  --subnet $(FAKELAB_SUBNET) --profile fakelab-outdated --profile fakelab
	$(COMPOSE_FAKELAB) exec -T api netops devices list

fakelab-accuracy: ## Compare the inventory with lab/fakelab/topology.yaml (precision/recall)
	set -a && . ./deploy/.env && set +a && cd backend && \
	POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$${DB_HOST_PORT:-5433}" \
	uv run python ../tools/eval/discovery_accuracy.py ../lab/fakelab/topology.yaml

# A change scenario (netops_fakes.scenarios), applied inside the device's own container so
# its syslog leaves from the device's address. Optional: PORT=Gi1/0/2 VLAN=20 TEXT="..."
# CHANGE_USER=jdoe SOURCE_IP=192.0.2.77.
DEVICE ?= dist1
SCENARIO ?= remove-vlan-from-trunk
CHANGE_USER ?= jdoe
SOURCE_IP ?= 192.0.2.77
fakelab-change: ## Change a fake device (DEVICE=dist1 SCENARIO=remove-vlan-from-trunk) + syslog
	$(COMPOSE_FAKELAB) exec -T fake-$(DEVICE) python -m netops_fakes.change apply \
	  /lab/topology.yaml $(DEVICE) $(SCENARIO) --user "$(CHANGE_USER)" --source-ip "$(SOURCE_IP)" \
	  $(if $(PORT),--port "$(PORT)") $(if $(VLAN),--vlan "$(VLAN)") $(if $(TEXT),--text "$(TEXT)")

fakelab-reset: ## Undo every fake lab change (no syslog: the next backup records the revert)
	$(COMPOSE_FAKELAB) exec -T fake-core1 python -m netops_fakes.change reset /lab/topology.yaml

fakelab-backup: ## Back up every managed device's configuration now (as the nightly job does)
	$(COMPOSE_FAKELAB) exec -T api netops configs backup

fakelab-down: ## Stop the whole stack including the fake lab (start again with make up)
	$(COMPOSE_FAKELAB) down
