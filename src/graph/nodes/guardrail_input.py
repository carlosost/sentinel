"""`guardrail_input` node (ADR-004, ADR-009 — Feature 03).

The graph's first real node: moderates the raw alert text on entry and routes
to `reject` on an unsafe verdict, `router` otherwise. As of Feature 13
(ADR-019), `guardrail_check` makes a real Llama Guard 3-8B call through the
gateway rather than the Feature 01 stub that always returned "safe" — this
node's own routing contract is unchanged, since it only ever read
`verdict["verdict"]`.
"""

from __future__ import annotations

from src.graph.state import IncidentState
from src.guardrails.check import guardrail_check

# Conditional-edge path_map keys for this node (used by build.py).
ROUTE_SAFE = "safe"
ROUTE_UNSAFE = "unsafe"


def guardrail_input(state: IncidentState) -> dict:
    """Run input moderation and record the verdict. Routing is decided
    separately by `guardrail_input_route` (the path function passed to
    `add_conditional_edges`), per real LangGraph's node/router split."""
    verdict = guardrail_check(state["raw_alert"], direction="input")
    return {"guardrail_input_verdict": verdict}


def guardrail_input_route(state: IncidentState) -> str:
    """Path function for the conditional edge out of `guardrail_input`."""
    verdict = state["guardrail_input_verdict"]
    return ROUTE_UNSAFE if verdict["verdict"] == "unsafe" else ROUTE_SAFE
