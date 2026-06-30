#!/usr/bin/env bash
# Preflight LLM-credential check (companion to ADR-021's "never silently
# default" convention, extended to infra startup).
#
# Run automatically by the Makefile before any target that talks to the real
# LiteLLM proxy (`make up`, `make smoke`, `make test`, `make shell`). Loads
# infra/.env if present, then checks that every required provider credential
# is both *set* and *not still a placeholder* from infra/.env.example. If
# anything is missing, fails loudly with the exact list of what to fix —
# instead of letting the failure surface three layers deep inside the
# litellm container's logs as an opaque auth error.
#
# Usage: bash scripts/check_env.sh
# (Portable to bash 3.2 — no associative arrays — since this also has to run
# on a stock macOS /bin/bash.)

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

# Parallel indexed arrays (not associative — bash 3.2 compatible):
# REQUIRED_VARS[i] is backed-by description REQUIRED_DESCR[i].
#
# ANTHROPIC_API_KEY and COHERE_API_KEY removed (ADR-023, Feature 15, Phase 2) —
# the fallback aliases they backed now resolve to local Ollama-served models
# (infra/litellm_config.yaml), which need no API key. See docs/MIGRATION_PLAN.md /
# docs/PROJECT_MEMORY.md ADR-023.
REQUIRED_VARS=(OPENAI_API_KEY TOGETHERAI_API_KEY)
REQUIRED_DESCR=(
  "sentinel-router, sentinel-grader, sentinel-diagnose, sentinel-propose-action, sentinel-postmortem, sentinel-judge, sentinel-embedding, sentinel-guardrail-fallback"
  "sentinel-guardrail"
)

missing=()
missing_descr=()
placeholder=()
placeholder_descr=()

for i in "${!REQUIRED_VARS[@]}"; do
  var="${REQUIRED_VARS[$i]}"
  descr="${REQUIRED_DESCR[$i]}"
  value="${!var:-}"
  if [[ -z "$value" ]]; then
    missing+=("$var")
    missing_descr+=("$descr")
  elif [[ "$value" == REPLACE_ME* ]]; then
    placeholder+=("$var")
    placeholder_descr+=("$descr")
  fi
done

if [[ ${#missing[@]} -eq 0 && ${#placeholder[@]} -eq 0 ]]; then
  printf "${GREEN}${BOLD}\xe2\x9c\x93 All required LLM provider credentials are set in %s.${RESET}\n" "$ENV_FILE"
  exit 0
fi

printf "${RED}${BOLD}\xe2\x9c\x97 Sentinel can't start the LiteLLM proxy — missing LLM credentials in %s:${RESET}\n\n" "$ENV_FILE"

for i in "${!missing[@]}"; do
  printf "  ${RED}\xe2\x9c\x97 %-20s${RESET} not set at all      ${YELLOW}(backs: %s)${RESET}\n" "${missing[$i]}" "${missing_descr[$i]}"
done
for i in "${!placeholder[@]}"; do
  printf "  ${RED}\xe2\x9c\x97 %-20s${RESET} still a placeholder ${YELLOW}(backs: %s)${RESET}\n" "${placeholder[$i]}" "${placeholder_descr[$i]}"
done

printf "\n  Fix: edit %s and set a real value for the line(s) above,\n" "$ENV_FILE"
printf "  then re-run: make check-env\n\n"
printf "  (LITELLM_VIRTUAL_KEY is intentionally not checked here — it's optional\n"
printf "  for local dev. See %s for details.)\n" "$EXAMPLE_FILE"

exit 1
