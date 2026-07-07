"""
`propose_action` node (ADR-013): produces a structured `{tool, args}`
remediation proposal via a single structured-output call through
`client_factory.get_chat_client(...)`, then attaches `side_effecting` by
looking the chosen tool up in `src.tools.registry` — never by trusting a
`side_effecting` value the LLM response might itself include.

**Trust boundary (this feature's one genuinely new design decision beyond
ADR-013's prose):** the LLM call's JSON schema is `{"tool": str, "args":
dict}` only. Even if a response includes an extra `"side_effecting"` key, it
is ignored — `state.proposed_action["side_effecting"]` always comes from
`src.tools.registry.get_tool_spec`. This matters because
`await_human_approval`/`execute` (roadmap items 9-10) will gate real
side-effecting actions on this flag; trusting an LLM-supplied boolean here
would mean a prompt-injected or hallucinated `"side_effecting": false` could
skip human approval for a genuinely destructive action.

A `tool` name absent from the registry is a hard error (`ProposeActionError`),
never silently treated as non-side-effecting — the same "never silently
default" discipline as `RouterError`/`RetrieverError`/`GradeDocumentsError`.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from src.gateway.client_factory import get_chat_client
from src.graph.state import IncidentState
from src.tools.registry import TOOL_REGISTRY, UnknownToolError, get_tool_spec

_PROMPT_TEMPLATE = """You are an SRE remediation-proposal assistant. Given the \
diagnosis below, propose exactly one remediation tool call. You MUST choose \
from the following tools only:

{tool_list}

Respond with strict JSON only, no prose: {{"tool": <string>, "args": <object>}}.

Diagnosis:
{diagnosis}
"""


def _format_tool_list() -> str:
    """Build the tool inventory injected into the LLM prompt.

    This exists because without an explicit tool list the LLM hallucinated
    tool names from its training data (e.g. `kubectl`) that are not in the
    registry — causing a hard `ProposeActionError` on every real-infra run.
    Enumerating valid tool names in the prompt eliminates that failure mode
    by constraining the model's choice space to names that `get_tool_spec`
    will actually accept.  The `side_effecting` tag is included so the model
    has context about the risk level of each tool (read-only vs. destructive).
    """
    lines = []
    for name, spec in TOOL_REGISTRY.items():
        tag = "side-effecting" if spec["side_effecting"] else "read-only"
        lines.append(f"  - {name} ({tag})")
    return "\n".join(lines)


class ProposeActionError(RuntimeError):
    """Raised when the proposal call's response is missing/invalid 'tool', or
    names a tool absent from the registry — never silently defaulted to a
    placeholder tool or an assumed side_effecting value."""


def _build_prompt(diagnosis: str) -> str:
    return _PROMPT_TEMPLATE.format(
        tool_list=_format_tool_list(),
        diagnosis=diagnosis,
    )


def propose_action(state: IncidentState) -> Dict[str, Any]:
    diagnosis = state.get("diagnosis") or ""

    client = get_chat_client(model="sentinel-propose-action")
    raw_response = client.invoke(_build_prompt(diagnosis))

    try:
        payload = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProposeActionError(
            f"propose_action response was not valid JSON: {exc}"
        ) from exc

    tool = payload.get("tool")
    if not tool:
        raise ProposeActionError(f"propose_action response missing/empty 'tool': {tool!r}")

    args = payload.get("args")
    if args is None:
        args = {}

    try:
        side_effecting = get_tool_spec(tool)["side_effecting"]
    except UnknownToolError as exc:
        raise ProposeActionError(str(exc)) from exc

    return {
        "proposed_action": {
            "tool": tool,
            "args": args,
            "side_effecting": side_effecting,
        }
    }
