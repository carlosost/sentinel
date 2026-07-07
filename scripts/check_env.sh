#!/usr/bin/env bash
# Preflight credential + config check (companion to ADR-021's "never silently
# default" convention, extended to infra startup).
#
# Run automatically by the Makefile before any target that talks to the real
# LiteLLM proxy (`make up`, `make smoke`, `make test`, `make shell`,
# `make bootstrap`). Loads infra/.env if present, then validates two groups:
#
#   REQUIRED_VARS  — LLM provider API keys (scanned by
#                    tests/gateway/test_check_env_credentials_match_config.py
#                    for drift against litellm_config.yaml — do not add
#                    non-provider vars here).
#   APP_VARS       — App-level config values needed by host-side scripts
#                    (make ingest, make eval, make smoke). Not provider keys;
#                    not covered by the drift test.
#
# Both groups must be set and must not be REPLACE_ME* placeholders.
# Exits non-zero with a readable error listing exactly what to fix.
#
# Usage: bash scripts/check_env.sh
# (Portable to bash 3.2 — no associative arrays — macOS /bin/bash compatible.)

set -uo pipefail

ENV_FILE="infra/.env"
EXAMPLE_FILE="infra/.env.example"

BOLD=$'\033[1m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; GREEN=$'\033[0;32m'; RESET=$'\033[0m'

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  printf "${RED}${BOLD}\xe2\x9c\x97 %s not found.${RESET}\n" "$ENV_FILE"
  printf "  Run: cp %s %s\n  then fill in real credentials.\n" "$EXAMPLE_FILE" "$ENV_FILE"
  exit 1
fi

# ---------------------------------------------------------------------------
# Group 1: LLM provider API keys
# Scanned by tests/gateway/test_check_env_credentials_match_config.py for
# drift against litellm_config.yaml provider prefixes — keep this array
# containing ONLY provider API keys, nothing else.
#
# ANTHROPIC_API_KEY and COHERE_API_KEY removed (ADR-023, Feature 15, Phase 2).
# TOGETHERAI_API_KEY removed (ADR-023 Phase 5, 2026-07-06) — sentinel-guardrail
# migrated to ollama_chat/llama-guard3:8b. See docs/PROJECT_MEMORY.md ADR-023.
# ---------------------------------------------------------------------------
REQUIRED_VARS=(OPENAI_API_KEY)
REQUIRED_DESCR=(
  "sentinel-router/grader/diagnose/propose-action/postmortem/judge/embedding/guardrail-fallback"
)

# ---------------------------------------------------------------------------
# Group 2: App-level config
# Needed by host-side scripts (make ingest, make eval, make smoke) and the
# FastAPI server. Not provider keys; not scanned by the drift test.
# ---------------------------------------------------------------------------
APP_VARS=(LITELLM_PROXY_URL LANGSMITH_API_KEY OLLAMA_BASE_URL)
APP_DESCR=(
  "LiteLLM proxy URL for host-side scripts (should be http://localhost:4000)"
  "LangSmith tracing + make eval evaluator calls"
  "Ollama base URL for host-side scripts (should be http://localhost:11434)"
)

missing=()
missing_descr=()
placeholder=()
placeholder_descr=()

_check_vars() {
  local -a vars=("${!1}")
  local -a descrs=("${!2}")
  for i in "${!vars[@]}"; do
    local var="${vars[$i]}"
    local descr="${descrs[$i]}"
    local value="${!var:-}"
    if [[ -z "$value" ]]; then
      missing+=("$var")
      missing_descr+=("$descr")
    elif [[ "$value" == REPLACE_ME* ]]; then
      placeholder+=("$var")
      placeholder_descr+=("$descr")
    fi
  done
}

_check_vars REQUIRED_VARS[@] REQUIRED_DESCR[@]
_check_vars APP_VARS[@] APP_DESCR[@]

if [[ ${#missing[@]} -eq 0 && ${#placeholder[@]} -eq 0 ]]; then
  printf "${GREEN}${BOLD}\xe2\x9c\x93 All required credentials and config are set in %s.${RESET}\n" "$ENV_FILE"
  exit 0
fi

printf "${RED}${BOLD}\xe2\x9c\x97 Sentinel preflight failed — fix these entries in %s:${RESET}\n\n" "$ENV_FILE"

for i in "${!missing[@]}"; do
  printf "  ${RED}\xe2\x9c\x97 %-22s${RESET} not set at all      ${YELLOW}(used by: %s)${RESET}\n" "${missing[$i]}" "${missing_descr[$i]}"
done
for i in "${!placeholder[@]}"; do
  printf "  ${RED}\xe2\x9c\x97 %-22s${RESET} still a placeholder ${YELLOW}(used by: %s)${RESET}\n" "${placeholder[$i]}" "${placeholder_descr[$i]}"
done

printf "\n  Fix: edit %s and set real values for the line(s) above,\n" "$ENV_FILE"
printf "  then re-run: make check-env\n\n"
printf "  (LITELLM_VIRTUAL_KEY is intentionally not checked — optional for local dev.)\n"

exit 1
