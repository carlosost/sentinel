# ==============================================================================
#  Sentinel — Autonomous SRE Incident Copilot — Developer Makefile
#
#  Status note: there is no long-running app/API container yet (Open Question
#  #10, docs/PROJECT_MEMORY.md §7) — that lands around roadmap items 9-10. Until
#  then, `app` is a one-shot container: `make smoke`/`make test`/`make shell`
#  each run it fresh via `docker compose run --rm`, not `docker exec` into an
#  already-running process.
#
#  Two ways to run tests — pick based on what's available:
#
#    make test         Full suite, real deps, inside Docker (langgraph,
#                      langchain-openai, pytest — via requirements.txt in the
#                      image). Requires Docker.
#    make test-local   Same test files, run with stdlib `unittest` directly on
#                      the host — no Docker, no network required. This is how
#                      Feature 01 was actually verified in a sandbox with no
#                      PyPI egress (ADR-021); it exercises the stdlib shims in
#                      src/gateway/client_factory.py and src/graph/_compat.py,
#                      not the real langgraph/langchain-openai libraries.
#
#  Quick reference:
#
#    make check-env     Verify infra/.env has real LLM provider credentials
#                         (run automatically before up/smoke/test/shell)
#    make build         Build the app image
#    make up            Start Postgres + Redis + LiteLLM + Ollama (infra only)
#    make pull-local-models  Pull local Ollama models for the fallback migration
#                         (ADR-023, Feature 15 — separate step, not part of `up`
#                         until Phase 4 cutover, since these are multi-GB pulls)
#    make down          Stop infra containers (volumes preserved)
#    make clean         Stop infra AND wipe all Docker volumes
#    make smoke         One-shot smoke check (graph builds, gateway/guardrail wired)
#    make test          Full pytest suite inside Docker (real deps)
#    make test-local    Deterministic-tier tests via stdlib unittest (no Docker)
#    make lint          Run the ADR-006 gateway-usage lint script
#    make eval          Run the eval harness (Probabilistic Tier, ADR-008)
#    make ingest        Ingest corpora/ into the documents store (ADR-010;
#                         fails in this sandbox — no LiteLLM proxy/real
#                         embedding client here, see Open Question #15)
#    make shell         Interactive shell inside the app image
#    make shell-db      psql session inside the postgres container
#    make logs          Tail infra service logs
#    make help          Print this help screen
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
  smoke test test-local lint eval ingest \
  pull-local-models \
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

## up           |  Start Postgres, Redis, LiteLLM, and Ollama (infra only)
up: check-env
	@printf "$(CYAN)$(BOLD)▶ Starting infra (postgres, redis, litellm, ollama)...$(RESET)\n"
	@$(COMPOSE) up --detach postgres redis litellm ollama
	@printf "$(GREEN)✓ Infra running. (No app/API server yet — see Open Question #10.)$(RESET)\n"
	@printf "$(YELLOW)  Local fallback models (ADR-023) are not pulled yet — run 'make pull-local-models'.$(RESET)\n"

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

## smoke        |  One-shot smoke check: graph builds, gateway/guardrail wired
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
	@$(COMPOSE) logs --follow postgres redis litellm ollama

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
eval:
	@printf "$(CYAN)$(BOLD)▶ Running eval harness...$(RESET)\n"
	@python3 scripts/run_eval.py

## ingest       |  Ingest corpora/ into the documents store (ADR-010)
ingest:
	@printf "$(CYAN)$(BOLD)▶ Running corpus ingestion...$(RESET)\n"
	@python3 scripts/ingest_corpora.py

## pull-local-models  |  Pull local Ollama fallback models (ADR-023, Feature 15)
pull-local-models:
	@printf "$(CYAN)$(BOLD)▶ Pulling local fallback models into ollama...$(RESET)\n"
	@bash scripts/pull_local_models.sh
	@printf "$(GREEN)✓ Local models ready.$(RESET)\n"

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
	@printf "\n$(BOLD)Note:$(RESET) no HTTP API/app server exists yet (Open Question #10).\n"
	@printf "  'app' is a one-shot container — make test/smoke/shell each start it fresh.\n\n"
