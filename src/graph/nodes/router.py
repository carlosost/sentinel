"""
`router` node (ADR-010): classifies the incoming alert into exactly one of
the three corpora (`runbooks`, `postmortems`, `infra_code_docs`) via a single
structured-output call through `client_factory.get_chat_client(...)`. Writing
`state.route` is the node's only state mutation — it does not retrieve
documents itself (that's `retriever`, roadmap item 5 / Feature 05).

Multi-corpus fan-out is explicitly out of scope per ADR-010 (Open Question
#7) — a route that isn't exactly one of `VALID_ROUTES` is a hard error, not a
best-effort fallback, since silently picking a default corpus would be a
worse failure mode than failing loudly.

v1 reads `state["raw_alert"]` directly. ADR-012 (Feature 06) introduces
`state.current_query` (init = raw_alert, overwritten on self-RAG retry); once
that field exists, this node must read it (falling back to raw_alert) instead
of raw_alert directly — see this feature's "Forward Note" in
memory/features/feature-04-ingestion-router-node.md. Nothing here asserts
current_query already exists.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from src.gateway.client_factory import get_chat_client
from src.graph.state import IncidentState

VALID_ROUTES = ("runbooks", "postmortems", "infra_code_docs")

_PROMPT_TEMPLATE = """You are an SRE incident routing classifier. Read the \
alert below and classify it into exactly one of these corpora: runbooks, \
postmortems, infra_code_docs. Respond with strict JSON only, no prose: \
{{"route": "<one of the three corpus names>"}}.

Alert:
{alert_text}
"""


class RouterError(RuntimeError):
    """Raised when the router's classification call returns a missing or
    invalid route — never silently coerced to a default corpus."""


def _build_prompt(alert_text: str) -> str:
    return _PROMPT_TEMPLATE.format(alert_text=alert_text)


def router(state: IncidentState) -> Dict[str, Any]:
    query = state["raw_alert"]
    client = get_chat_client(model="sentinel-router")
    raw_response = client.invoke(_build_prompt(query))

    try:
        payload = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RouterError(f"router classification response was not valid JSON: {exc}") from exc

    route = payload.get("route")
    if route not in VALID_ROUTES:
        raise RouterError(
            f"router classification returned an invalid route: {route!r} "
            f"(expected one of {VALID_ROUTES})"
        )
    return {"route": route}
