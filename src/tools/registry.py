"""
Static tool registry (ADR-013): the single source of truth for whether a given
remediation tool is `side_effecting`. `propose_action` looks up this flag by
tool name rather than trusting any `side_effecting` value an LLM response might
include — see `propose_action.py`'s docstring for why that trust boundary
matters.

Seeded with three side-effecting tools (`restart_service`, `rollback_deploy`,
`page_secondary_oncall`) and one read-only tool (`fetch_additional_logs`) — the
read-only entry exists specifically so §5.2's `guardrail_output -(read-only
action)-> execute` branch (roadmap items 8/10) is reachable at all; without at
least one `side_effecting=False` tool, that edge would be permanently dead code.

This is a static, in-process dict, not a database table or a gateway-fronted
call — ADR-013 never proposed a runtime/dynamic registry, and nothing about
tool side-effect classification needs to be model-served.
"""

from __future__ import annotations

from typing import Dict, TypedDict


class ToolSpec(TypedDict):
    side_effecting: bool


TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "restart_service": {"side_effecting": True},
    "rollback_deploy": {"side_effecting": True},
    "page_secondary_oncall": {"side_effecting": True},
    "fetch_additional_logs": {"side_effecting": False},
}


class UnknownToolError(RuntimeError):
    """Raised when a tool name isn't in `TOOL_REGISTRY` — never silently
    treated as non-side-effecting, since that would be the worse failure mode
    (a real side-effecting action skipping human approval)."""


def get_tool_spec(tool_name: str) -> ToolSpec:
    try:
        return TOOL_REGISTRY[tool_name]
    except KeyError as exc:
        raise UnknownToolError(
            f"'{tool_name}' is not a known tool (expected one of "
            f"{sorted(TOOL_REGISTRY)})"
        ) from exc


def is_side_effecting(tool_name: str) -> bool:
    return get_tool_spec(tool_name)["side_effecting"]
