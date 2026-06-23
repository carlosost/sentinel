"""
`guardrail_output` node (ADR-004, ADR-014 — Feature 08).

Reused at two call sites per ADR-014: pre-execution (`propose_action ->
guardrail_output`, moderating the proposed remediation explanation) and
post-execution (the future `write_postmortem -> guardrail_output`, roadmap
item 11, moderating the postmortem draft). One node function, one conditional-
edge routing function (`guardrail_output_route`) serve both — the two
positions are told apart by checking `state["execution_result"]` rather than
by graph position, since `execution_result` is unset pre-execution and set
post-execution (ADR-014's own framing).

Still calls the Feature 01 stub `guardrail_check` (moderation accuracy is
roadmap item 13/ADR-019) — this feature wires the real call site/routing
contract around it, completing the retrofit ADR-009 deferred (Open Question
#6).

Implementation note (not pinned by ADR-014's text, decided here): the
moderated `text` differs by call site since there's no single field that
makes sense for both — pre-execution moderates a rendering of
`diagnosis`/`proposed_action` (the "proposed remediation explanation" ADR-014
names); post-execution moderates `postmortem_draft` once it exists. Until
`write_postmortem` lands (roadmap item 11), only the pre-execution rendering
is reachable.
"""

from __future__ import annotations

from src.graph.state import IncidentState
from src.guardrails.check import guardrail_check

# Conditional-edge path_map keys for this node (used by build.py).
ROUTE_REJECT = "reject"
ROUTE_AWAIT_APPROVAL = "await_human_approval"
ROUTE_EXECUTE = "execute"
ROUTE_END = "end"


def _render_output_text(state: IncidentState) -> str:
    """Render the text to moderate for this call site. Post-execution
    (`postmortem_draft` set) takes precedence once it exists; pre-execution
    falls back to a rendering of `diagnosis`/`proposed_action`."""
    postmortem_draft = state.get("postmortem_draft")
    if postmortem_draft:
        return postmortem_draft

    diagnosis = state.get("diagnosis") or ""
    proposed_action = state.get("proposed_action") or {}
    return f"{diagnosis}\n\nProposed action: {proposed_action}"


def guardrail_output(state: IncidentState) -> dict:
    """Run output moderation on this call site's rendered text and record the
    verdict. Routing is decided separately by `guardrail_output_route`."""
    verdict = guardrail_check(_render_output_text(state), direction="output")
    return {"guardrail_output_verdict": verdict}


def guardrail_output_route(state: IncidentState) -> str:
    """Path function for the conditional edge out of `guardrail_output`
    (ADR-014). Distinguishes the pre-execution and post-execution call sites
    via `state["execution_result"]`, not graph position, since both call
    sites share this one node/routing function."""
    verdict = state["guardrail_output_verdict"]
    if verdict["verdict"] == "unsafe":
        return ROUTE_REJECT

    if state.get("execution_result") is not None:
        # Post-execution call site (write_postmortem -> guardrail_output).
        # execution_result is preserved in state regardless (ADR-014) — this
        # node never clears it.
        return ROUTE_END

    # Pre-execution call site (propose_action -> guardrail_output).
    proposed_action = state["proposed_action"]
    return ROUTE_AWAIT_APPROVAL if proposed_action["side_effecting"] else ROUTE_EXECUTE
