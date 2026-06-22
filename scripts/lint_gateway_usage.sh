#!/usr/bin/env bash
# ADR-006: every LLM/embedding client must be constructed only via
# src/gateway/client_factory.py. This script fails CI if any other file imports a
# provider SDK directly or constructs a provider client outside that module.
#
# Scans src/ and scripts/ only (production code) — never tests/, since tests
# legitimately reference these patterns as string fixtures (see
# tests/test_lint_gateway_usage.py) without that being a real violation.
#
# Accepts an optional first argument: the directory to treat as repo root. Used by
# the test suite to point this at a synthetic /tmp fixture tree instead of the real
# repo, so testing "does this fail correctly" never requires writing a violating
# file into the actual project.
set -euo pipefail

TARGET_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$TARGET_ROOT"

# Patterns that indicate a direct provider SDK usage.
PATTERN='(^|[^.])\b(import openai|from openai|import anthropic|from anthropic|ChatOpenAI\(|OpenAIEmbeddings\(|ChatAnthropic\()'

SCAN_DIRS=()
[ -d "src" ] && SCAN_DIRS+=("src")
[ -d "scripts" ] && SCAN_DIRS+=("scripts")

if [ "${#SCAN_DIRS[@]}" -eq 0 ]; then
  echo "Gateway lint: nothing to scan (no src/ or scripts/ under $TARGET_ROOT)."
  exit 0
fi

VIOLATIONS=$(grep -RnE "$PATTERN" \
  --include="*.py" \
  --exclude-dir=".git" \
  --exclude-dir="gateway" \
  --exclude-dir=".venv" \
  --exclude-dir="venv" \
  "${SCAN_DIRS[@]}" || true)

if [ -n "$VIOLATIONS" ]; then
  echo "Gateway lint failed (ADR-006): direct provider SDK usage found outside src/gateway/:"
  echo "$VIOLATIONS"
  exit 1
fi

echo "Gateway lint passed: no direct provider SDK usage outside src/gateway/."
exit 0
