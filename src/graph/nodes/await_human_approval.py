"""
`await_human_approval` node (ADR-002, ADR-015 — Feature 09).

Pauses the graph durably (via `_compat.py`'s `interrupt()`/checkpointer
addendum, standing in for real langgraph `interrupt()` + `PostgresSaver`) for
any `proposed_action.side_effecting == True` run that reaches it from
`guardrail_output`'s safe branch (ADR-014). Resumes once a human's decision is
written into `state.human_decision` (the `HumanDecision` shape ADR-015 pins,
in `src/graph/state.py`) via `update_state`, then `invoke(None, config=...)`.

**Why this node checks state instead of using `interrupt()`'s return value:**
this shim's `interrupt()` always raises — it cannot return a value to the
caller the way real langgraph's generator-replay mechanism does (see
`_compat.py`'s ADDENDUM docstring). So this node is written to be safely
re-run on resume: it interrupts only when `human_decision` is still unset,
and falls through to a no-op return once it's been written back. This means
the node's *body* re-executes on resume (cheap and side-effect-free here),
not that `interrupt()` itself returns anything — a deliberate, documented
shim limitation, not a faithful generator-replay.
"""

from __future__ import annotations

from typing import Any, Dict

from src.graph._compat import interrupt
from src.graph.state import IncidentState

# Conditional-edge path_map keys for this node (used by build.py).
ROUTE_APPROVED = "approved"
ROUTE_REJECTED = "rejected"


def await_human_approval(state: IncidentState) -> Dict[str, Any]:
    """Interrupt (pause) until `human_decision` is set; no-op once it is."""
    if state.get("human_decision") is not None:
        return {}

    interrupt({"proposed_action": state.get("proposed_action")})
    return {}  # unreachable — interrupt() always raises (see module docstring)


def await_human_approval_route(state: IncidentState) -> str:
    """Path function for the conditional edge out of `await_human_approval`.
    Only ever called after the node returns without interrupting, i.e. once
    `human_decision` is set."""
    decision = state["human_decision"]
    return ROUTE_APPROVED if decision["approved"] else ROUTE_REJECTED


def resolve_action(state: IncidentState) -> dict:
    """ADR-015's `modified_action` precedence rule: on an approved decision,
    `human_decision.modified_action` wins over `proposed_action` whenever it
    is not `None`, falling back to `proposed_action` otherwise.

    Forward groundwork for `execute` (roadmap item 10), the same
    "compute now, consume later" pattern Feature 07 used for
    `proposed_action.side_effecting` — `execute` is specified to call this
    function rather than re-deriving the precedence rule itself, so the two
    can never drift.
    """
    decision = state["human_decision"]
    modified_action = decision.get("modified_action")
    return modified_action if modified_action is not None else state["proposed_action"]
