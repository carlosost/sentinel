"""`guardrail_input` node (ADR-004, ADR-009 — Feature 03).

The graph's first real node: moderates the raw alert text on entry and routes
to `reject` on an unsafe verdict, `router` otherwise. The moderation decision
itself is still the Feature 01 stub (`guardrail_check` always returns "safe")
— this feature wires the real call site and the real routing contract around
it, per ADR-004's original promise. Unstubbing lands at roadmap item 13
(ADR-019) and changes none of this file.
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
