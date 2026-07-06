#!/usr/bin/env bash
# Container entrypoint (ADR-024 — HTTP API now exists, Open Question #10 resolved).
#
# Usage (first arg selects a mode; anything else is exec'd directly):
#   serve   (default) — start the FastAPI HTTP server (uvicorn src.api.app:app,
#             port 8000). Requires DATABASE_URL. This is the production mode.
#   smoke   — one-shot graph build + gateway wiring check. Used by `make smoke`
#             to verify the image is correctly wired without starting a server.
#   test    — run the full real pytest suite (requires real packages via
#             requirements.txt; image's job, not the dev sandbox's; see ADR-021).
#   shell / bash — drop into an interactive shell.
#   anything else — exec'd as-is.
set -euo pipefail

case "${1:-serve}" in
  serve)
    exec uvicorn src.api.app:app --host 0.0.0.0 --port 8000
    ;;
  ingest)
    exec python3 scripts/ingest_corpora.py
    ;;
  eval)
    exec python3 scripts/run_eval.py
    ;;
  smoke)
    exec python3 -c "
import os
os.environ.setdefault('LITELLM_PROXY_URL', os.environ.get('LITELLM_PROXY_URL', 'http://litellm:4000'))

from src.graph.build import build_graph
from src.guardrails.check import guardrail_check
from src.gateway.client_factory import get_chat_client

graph = build_graph()
result = graph.invoke({
    'raw_alert': 'smoke-test alert',
    'guardrail_input_verdict': None,
    'guardrail_output_verdict': None,
    'route': None,
    'retrieved_docs': [],
    'reranked_docs': [],
    'relevance_grade': None,
    'retry_count': 0,
    'diagnosis': None,
    'proposed_action': None,
    'human_decision': None,
    'execution_result': None,
    'postmortem_draft': None,
    'thread_id': 'smoke-test',
})
assert result['raw_alert'] == 'smoke-test alert'

verdict = guardrail_check('smoke test', direction='input')
assert verdict['verdict'] == 'safe'

client = get_chat_client(model='sentinel-router')
assert client is not None

print('Sentinel image smoke check passed: graph builds, guardrail stub responds, gateway client constructs.')
print('HTTP API: start with entrypoint.sh serve (uvicorn src.api.app:app --host 0.0.0.0 --port 8000).')
"
    ;;
  test)
    shift
    exec pytest "$@"
    ;;
  shell|bash)
    exec bash
    ;;
  *)
    exec "$@"
    ;;
esac
