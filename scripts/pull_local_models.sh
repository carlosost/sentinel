#!/usr/bin/env bash
# ADR-023 (Feature 15, Phase 1): pulls every model the local-fallback migration's
# Ollama-served aliases depend on (infra/litellm_config.yaml, Phase 2). Idempotent —
# `ollama pull` no-ops if the model is already present at that tag.
#
# Ollama runs on the HOST for Metal GPU access (not in Docker) — this script calls
# the host `ollama` CLI directly. Ensure Ollama is running before calling:
#   OLLAMA_HOST=0.0.0.0 ollama serve
set -euo pipefail

MODELS=(
  "llama3.1:8b-instruct-q4_K_M"
  "mistral-small:24b-instruct-2501-q4_K_M"
  "bge-m3"
  "llama-guard3:8b"   # sentinel-guardrail primary (ADR-023 Phase 5, 2026-07-06)
)

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: 'ollama' not found on PATH. Install it with: brew install ollama" >&2
  exit 1
fi

for m in "${MODELS[@]}"; do
  echo "Pulling ${m} ..."
  ollama pull "${m}"
done

echo "All local fallback models pulled."
