#!/usr/bin/env bash
# ADR-023 (Feature 15, Phase 1): pulls every model the local-fallback migration's
# Ollama-served aliases depend on (infra/litellm_config.yaml, Phase 2). Idempotent —
# `ollama pull` no-ops if the model is already present at that tag.
#
# Requires the `ollama` service from infra/docker-compose.yml to already be running
# (`make up` starts it as a dependency of `litellm`). Run via `make pull-local-models`,
# not directly, so the compose file/project context is always correct.
set -euo pipefail

COMPOSE_FILE="infra/docker-compose.yml"

MODELS=(
  "llama3.1:8b-instruct-q4_K_M"
  "mistral-small:24b-instruct-2501-q4_K_M"
  "bge-m3"
)

COMPOSE_CMD="docker compose"
if ! docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
fi

for m in "${MODELS[@]}"; do
  echo "Pulling ${m} ..."
  ${COMPOSE_CMD} -f "${COMPOSE_FILE}" exec ollama ollama pull "${m}"
done

echo "All local fallback models pulled."
