"""
`write_postmortem` node (ADR-017): drafts a structured postmortem via one LLM
call through `client_factory.get_chat_client(...)`, covering four fixed
sections — Summary, Root Cause, Action Taken & Outcome, Notes — then always
routes to `guardrail_output` (a single static edge; `guardrail_output` infers
this is its post-execution call site by checking `state.execution_result`,
not by graph position, per ADR-014).

Reuses `await_human_approval.resolve_action`'s ADR-015 precedence rule for
"which action was actually taken" (`modified_action` over `proposed_action`)
rather than re-deriving it — the same "compute once, consume once" discipline
`execute` (Feature 10) already follows, guarded the same way: precedence only
applies once `human_decision` exists, since the safe+read-only path never
sets one.

Confidence-aware (ADR-017): when `diagnosis_confidence == "low"`, the Notes
section must mention degraded retrieval confidence. This is enforced as a
deterministic post-processing append rather than left solely to the model's
own prose, so the structural contract holds even if a given completion omits
it.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from src.gateway.client_factory import get_chat_client
from src.graph.nodes.await_human_approval import resolve_action
from src.graph.state import IncidentState

SECTION_SUMMARY = "Summary"
SECTION_ROOT_CAUSE = "Root Cause"
SECTION_ACTION_TAKEN = "Action Taken & Outcome"
SECTION_NOTES = "Notes"

LOW_CONFIDENCE_NOTE = (
    "This diagnosis was made under degraded retrieval confidence "
    "(diagnosis_confidence=low)."
)

_PROMPT_TEMPLATE = """You are an SRE incident postmortem writer. Using the \
inputs below, draft a postmortem with exactly four sections, each starting \
with its own heading on its own line: "Summary", "Root Cause", \
"Action Taken & Outcome", "Notes". Respond with strict JSON only, no prose: \
{{"postmortem_draft": <string>}}.

Diagnosis:
{diagnosis}

Action taken:
{action}

Execution result:
{execution_result}

Human note (if any):
{human_note}
"""


class WritePostmortemError(RuntimeError):
    """Raised when the write_postmortem call's response is missing/invalid —
    never silently defaulted to an empty draft (same "never silently
    default" discipline as DiagnoseError/RouterError/GradeDocumentsError)."""


def _action_taken(state: IncidentState) -> dict:
    """ADR-015 precedence only applies once a human decision exists; the
    read-only path (no `await_human_approval` interrupt) always executed
    `proposed_action` unchanged — see `execute._action_to_execute`, the same
    rule applied at the node that actually ran the action."""
    if state.get("human_decision") is not None:
        return resolve_action(state)
    return state.get("proposed_action") or {}


def _build_prompt(state: IncidentState) -> str:
    human_decision = state.get("human_decision") or {}
    return _PROMPT_TEMPLATE.format(
        diagnosis=state.get("diagnosis") or "(no diagnosis)",
        action=_action_taken(state),
        execution_result=state.get("execution_result") or {},
        human_note=human_decision.get("note") or "(none)",
    )


def write_postmortem(state: IncidentState) -> Dict[str, Any]:
    client = get_chat_client(model="sentinel-postmortem")
    raw_response = client.invoke(_build_prompt(state))

    try:
        payload = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise WritePostmortemError(
            f"write_postmortem response was not valid JSON: {exc}"
        ) from exc

    draft = payload.get("postmortem_draft")
    if not draft:
        raise WritePostmortemError(
            f"write_postmortem response missing/empty 'postmortem_draft': {draft!r}"
        )

    if state.get("diagnosis_confidence") == "low" and LOW_CONFIDENCE_NOTE not in draft:
        draft = f"{draft}\n\n{LOW_CONFIDENCE_NOTE}"

    return {"postmortem_draft": draft}
