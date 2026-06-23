"""
`execute` node (ADR-016): runs the resolved remediation action via
`src.tools.executors.execute_tool`, then routes on outcome —
`-(success)-> write_postmortem`, `-(failure)-> diagnose`.

Reached two ways (§5.2): directly from `guardrail_output`'s safe+read-only
branch (no `human_decision` set — the action runs as originally proposed),
or from `await_human_approval`'s approved branch (`human_decision` set,
ADR-015's `modified_action` precedence applies). This node reuses
`await_human_approval.resolve_action` for the latter case rather than
re-deriving the precedence rule, so the two can never drift — the same
"compute once, consume once" discipline Feature 09 set up as forward
groundwork for exactly this node.
"""

from __future__ import annotations

from typing import Any, Dict

from src.graph.nodes.await_human_approval import resolve_action
from src.graph.state import IncidentState
from src.tools.executors import execute_tool

ROUTE_SUCCESS = "success"
ROUTE_FAILURE = "failure"


def _action_to_execute(state: IncidentState) -> dict:
    """ADR-015 precedence only applies once a human decision exists; the
    read-only path (no `await_human_approval` interrupt) always executes
    `proposed_action` unchanged."""
    if state.get("human_decision") is not None:
        return resolve_action(state)
    return state["proposed_action"]


def execute(state: IncidentState) -> Dict[str, Any]:
    action = _action_to_execute(state)
    result = execute_tool(action["tool"], action.get("args", {}))
    return {"execution_result": result}


def execute_route(state: IncidentState) -> str:
    """Path function for the conditional edge out of `execute`. Only ever
    called after the node returns, i.e. once `execution_result` is set."""
    return ROUTE_SUCCESS if state["execution_result"]["success"] else ROUTE_FAILURE
