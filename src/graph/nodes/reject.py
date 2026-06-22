"""`reject` node (ADR-009 — Feature 03).

Terminal node reached when `guardrail_input` (and, once Feature 08 retrofits
it per Open Question #16, `guardrail_output`) returns an unsafe verdict.
Records why the run was rejected and ends the graph — it performs no model
calls.
"""

from __future__ import annotations

from src.graph.state import IncidentState


def reject(state: IncidentState) -> dict:
    """Record the triggering guardrail verdict's reason as `rejection_reason`.

    Currently only `guardrail_input_verdict` can route here (Feature 03's
    scope); `guardrail_output_verdict` is wired in once Feature 08 retrofits
    its rejection branch (Open Question #16).
    """
    verdict = state.get("guardrail_input_verdict") or state.get("guardrail_output_verdict")
    reason = verdict["reason"] if verdict else "unknown"
    return {"rejection_reason": reason}
