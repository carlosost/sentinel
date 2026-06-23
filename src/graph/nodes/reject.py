"""`reject` node (ADR-009 — Feature 03; ADR-014 — Feature 08).

Terminal node reached when `guardrail_input` or `guardrail_output` returns an
unsafe verdict. Records why the run was rejected and ends the graph — it
performs no model calls.
"""

from __future__ import annotations

from src.graph.state import IncidentState


def reject(state: IncidentState) -> dict:
    """Record the triggering guardrail verdict's reason as `rejection_reason`.

    Either `guardrail_input_verdict` (Feature 03) or `guardrail_output_verdict`
    (Feature 08, ADR-014 — both the pre- and post-execution call sites) can
    route here. Both verdicts may be set and "safe" by the time this node
    runs (e.g. a safe input verdict followed by an unsafe output verdict) —
    picking "whichever is set" is wrong in that case, since it would report
    the safe one. The verdict whose own `verdict` field is "unsafe" is the
    one that actually triggered this route, so that's the one whose `reason`
    is reported; this never silently defaults to the wrong verdict's reason.
    """
    input_verdict = state.get("guardrail_input_verdict")
    output_verdict = state.get("guardrail_output_verdict")

    if input_verdict and input_verdict["verdict"] == "unsafe":
        reason = input_verdict["reason"]
    elif output_verdict and output_verdict["verdict"] == "unsafe":
        reason = output_verdict["reason"]
    else:
        reason = "unknown"

    return {"rejection_reason": reason}
