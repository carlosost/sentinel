#!/usr/bin/env bash
# Container entrypoint (ADR-021 era — no HTTP API exists yet, see Open Question #10).
#
# Usage (first arg selects a mode; anything else is exec'd directly):
#   smoke   (default) — import the package, build the graph, exercise the gateway
#           config check and the guardrail stub. Confirms the image is wired
#           correctly without requiring an API to exist yet.
#   test    — run the full real pytest suite (requires the real langgraph/
#             langchain-openai/pytest installed via requirements.txt — this is
#             the image's job, not the dev sandbox's; see ADR-021).
#   shell / bash — drop into an interactive shell.
#   anything else — exec'd as-is (e.g. a future `uvicorn src.api:app`).
set -euo pipefail

case "${1:-smoke}" in
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

client = get_chat_client(model='sentinel-chat')
assert client is not None

print('Sentinel image smoke check passed: graph builds, guardrail stub responds, gateway client constructs.')
print('No HTTP API exists yet (Open Question #10) — override CMD to run \"pytest\" or \"bash\" instead.')
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
