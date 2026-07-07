# ==============================================================================
#  Sentinel — Autonomous SRE Incident Copilot — Developer Makefile
#
#  Production boot sequence (first time):
#    1. cp infra/.env.example infra/.env  &&  edit infra/.env
#    2. make up               — start Postgres, Redis, LiteLLM, Ollama, mock-staging-api
#    3. make pull-local-models — pull Ollama models (~14 GB, one-time)
#    4. make init-db          — apply infra/schema.sql (pgvector table + indexes)
#    5. make ingest           — embed corpora/ into pgvector
#    6. make smoke            — verify graph + gateway + guardrail wiring
#    7. make serve            — start the FastAPI HTTP server (port 8000)
#
#  Two ways to run tests — pick based on what's available:
#
#    make test         Full suite, real deps, inside Docker (langgraph,
#                      langchain-openai, pytest — via requirements.txt in the
#                      image). Requires Docker.
#    make test-local   Same test files, run with stdlib `unittest` directly on
#                      the host — no Docker, no network required. Exercises the
#                      conditional-import shims (ADR-024) — real packages
#                      activate automatically when installed.
#
#  Quick reference:
#
#    make check-env          Verify infra/.env has real LLM provider credentials
#    make build              Build the app image
#    make up                 Start all infra services (Postgres, Redis, LiteLLM,
#                              Ollama, mock-staging-api)
#    make pull-local-models  Pull local Ollama models (ADR-023 + ADR-023-Phase5)
#    make init-db            Apply infra/schema.sql to Postgres (idempotent)
#    make down               Stop containers (volumes preserved)
#    make clean              Stop containers AND wipe all Docker volumes
#    make serve              Start the FastAPI HTTP server (ADR-024, port 8000)
#    make smoke              One-shot wiring check (no server started)
#    make test               Full pytest suite inside Docker (real deps)
#    make test-local         Deterministic-tier tests via stdlib unittest (no Docker)
#    make lint               Run the ADR-006 gateway-usage lint script
#    make eval               Run the eval harness (Probabilistic Tier, ADR-008)
#    make ingest             Ingest corpora/ into the documents store (ADR-010)
#    make shell              Interactive shell inside the app image
#    make shell-db           psql session inside the postgres container
#    make logs               Tail infra service logs
#    make help               Print this help screen
#
# ==============================================================================

# ------------------------------------------------------------------------------
# Project-level constants
# ------------------------------------------------------------------------------

COMPOSE_FILE     := infra/docker-compose.yml
ENV_FILE         := infra/.env

# Compose command — supports both `docker compose` (v2) and legacy `docker-compose`.
# --env-file is explicit (the bare `docker compose` default only looks for a
# `.env` next to wherever it's invoked from) so infra/.env is what actually
# feeds the ${VAR:?...} required-credential checks in docker-compose.yml,
# regardless of where `make` is run from.
COMPOSE          := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose") -f $(COMPOSE_FILE) --env-file $(ENV_FILE)

DB_SERVICE       := postgres
DB_CONTAINER     := $(shell basename $(CURDIR))-$(DB_SERVICE)-1
POSTGRES_USER    := sentinel
POSTGRES_DB      := sentinel

# Colour codes for terminal output
BOLD   := \033[1m
GREEN  := \033[0;32m
YELLOW := \033[0;33m
CYAN   := \033[0;36m
RESET  := \033[0m

# ------------------------------------------------------------------------------
# .PHONY — prevents make from confusing targets with files of the same name
# ------------------------------------------------------------------------------
.PHONY: \
  check-env build up down clean \
  bootstrap serve smoke test test-local lint eval ingest \
  pull-local-models init-db \
  shell shell-db logs \
  help

.DEFAULT_GOAL := help

# ==============================================================================
#  CREDENTIAL PREFLIGHT
# ==============================================================================

## check-env    |  Verify infra/.env has real (non-placeholder) LLM provider keys
check-env:
	@bash scripts/check_env.sh

# ==============================================================================
#  BUILD & INFRA LIFECYCLE
# ==============================================================================

## build        |  Build the app image
build:
	@printf "$(CYAN)$(BOLD)▶ Building app image...$(RESET)\n"
	@$(COMPOSE) build app
	@printf "$(GREEN)✓ Image built.$(RESET)\n"

## up           |  Start all infra services (Postgres, Redis, LiteLLM, mock-staging-api)
up: check-env
	@printf "$(CYAN)$(BOLD)▶ Starting infra...$(RESET)\n"
	@$(COMPOSE) up --detach postgres redis litellm mock-staging-api
	@printf "$(GREEN)✓ Infra running. Ollama runs on the host — start it with: OLLAMA_HOST=0.0.0.0 ollama serve$(RESET)\n"
	@printf "$(YELLOW)  Next: make pull-local-models → make init-db → make ingest → make serve$(RESET)\n"

## down         |  Stop containers (volumes preserved)
down:
	@printf "$(CYAN)$(BOLD)▶ Bringing down containers...$(RESET)\n"
	@$(COMPOSE) down --remove-orphans
	@printf "$(GREEN)✓ Containers removed.$(RESET)\n"

## clean        |  Stop containers AND delete all Docker volumes (full wipe)
clean:
	@printf "$(YELLOW)$(BOLD)⚠ Wiping containers and volumes...$(RESET)\n"
	@$(COMPOSE) down --volumes --remove-orphans
	@printf "$(GREEN)✓ Volumes wiped.$(RESET)\n"

# ==============================================================================
#  RUNNING THE APP IMAGE (one-shot — see header note)
# ==============================================================================

## bootstrap    |  Full first-time setup: up → pull-local-models → init-db → ingest → smoke → serve
bootstrap: check-env
	@printf "$(CYAN)$(BOLD)▶ Bootstrapping Sentinel from scratch...$(RESET)\n"
	@$(MAKE) up
	@$(MAKE) pull-local-models
	@$(MAKE) init-db
	@$(MAKE) ingest
	@$(MAKE) smoke
	@$(MAKE) serve
	@printf "$(GREEN)$(BOLD)✓ Bootstrap complete. API running at http://localhost:8000$(RESET)\n"

## serve        |  Start the FastAPI HTTP server (port 8000, ADR-024)
serve: check-env
	@printf "$(CYAN)$(BOLD)▶ Starting Sentinel HTTP API on port 8000...$(RESET)\n"
	@$(COMPOSE) up --detach app
	@printf "$(GREEN)✓ API running at http://localhost:8000$(RESET)\n"
	@printf "$(YELLOW)  Docs: http://localhost:8000/docs   Health: http://localhost:8000/healthz$(RESET)\n"

## smoke        |  One-shot wiring check: graph builds, gateway/guardrail wired
smoke: check-env
	@printf "$(CYAN)$(BOLD)▶ Running smoke check...$(RESET)\n"
	@$(COMPOSE) run --rm app smoke

## test         |  Full pytest suite inside Docker (real langgraph/langchain-openai/pytest)
test: check-env
	@printf "$(CYAN)$(BOLD)▶ Running full test suite (Docker, real deps)...$(RESET)\n"
	@$(COMPOSE) run --rm app test

## shell        |  Interactive shell inside the app image
shell: check-env
	@$(COMPOSE) run --rm app shell

## shell-db     |  Open a psql session inside the postgres container
shell-db:
	@$(COMPOSE) exec $(DB_SERVICE) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

## logs         |  Tail infra service logs  (Ctrl-C to exit)
logs:
	@$(COMPOSE) logs --follow postgres redis litellm mock-staging-api app

# ==============================================================================
#  HOST-ONLY (NO DOCKER REQUIRED)
# ==============================================================================

## test-local   |  Deterministic-tier tests via stdlib unittest — no Docker, no network
test-local:
	@printf "$(CYAN)$(BOLD)▶ Running tests locally via stdlib unittest...$(RESET)\n"
	@python3 -m unittest discover -s tests -v

## lint         |  Run the ADR-006 gateway-usage lint script
lint:
	@printf "$(CYAN)$(BOLD)▶ Running gateway-usage lint...$(RESET)\n"
	@bash scripts/lint_gateway_usage.sh

## eval         |  Run the eval harness (Probabilistic Tier, reported separately from tests)
eval: check-env
	@printf "$(CYAN)$(BOLD)▶ Running eval harness (inside Docker)...$(RESET)\n"
	@$(COMPOSE) run --rm app eval

## ingest       |  Ingest corpora/ into the documents store (ADR-010)
ingest: check-env
	@printf "$(CYAN)$(BOLD)▶ Running corpus ingestion (inside Docker)...$(RESET)\n"
	@$(COMPOSE) run --rm app ingest

## pull-local-models  |  Pull Ollama models: fallbacks + llama-guard3 (ADR-023 + Phase5)
pull-local-models:
	@printf "$(CYAN)$(BOLD)▶ Pulling local models into ollama...$(RESET)\n"
	@bash scripts/pull_local_models.sh
	@printf "$(GREEN)✓ Local models ready.$(RESET)\n"

## init-db      |  Apply infra/schema.sql to Postgres (idempotent — safe to re-run)
init-db:
	@printf "$(CYAN)$(BOLD)▶ Initialising Postgres schema (pgvector + documents table)...$(RESET)\n"
	@$(COMPOSE) exec -T $(DB_SERVICE) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		-f /dev/stdin < infra/schema.sql
	@printf "$(GREEN)✓ Schema applied.$(RESET)\n"

# ==============================================================================
#  HELP
# ==============================================================================

## help         |  Print available targets (default)
help:
	@printf "\n$(BOLD)Sentinel — Developer Makefile$(RESET)\n\n"
	@printf "$(BOLD)Usage:$(RESET)  make <target>\n\n"
	@printf "$(BOLD)Targets:$(RESET)\n"
	@awk 'BEGIN { FS = "  \\|  " } \
	      /^## /{ \
	        target=$$1; sub(/^## /,"",target); \
	        desc=$$2; \
	        printf "  $(CYAN)%-14s$(RESET) %s\n", target, desc \
	      }' $(MAKEFILE_LIST)
	@printf "\n$(BOLD)First-time boot:$(RESET) make up → make pull-local-models → make init-db → make ingest → make serve\n\n"
