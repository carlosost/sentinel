"""
Guardrail moderation hook (ADR-004, ADR-007, ADR-019).

v1 (Feature 01) stubbed this to always return "safe" so every call site could
wire up the contract before the real model existed. Feature 13 (ADR-019)
replaces the body with one real LLM call through
`client_factory.get_chat_client(model="sentinel-guardrail")` — the same
gateway-only, alias-based pattern ADR-018 established — backed by Llama Guard
3-8B with a configured fallback safety model. The function signature and
every call site (`guardrail_input`, `guardrail_output`) are unchanged.

`GuardrailVerdict`'s shape is now a fixed contract (ADR-019): strictly binary
`verdict` (no `borderline` state — corrects a stale §8.3 example that was
never implemented), plus a `category` field holding Llama Guard's taxonomy
code (e.g. "S1") when unsafe, `None` when safe.

Guardrail calls are normal `sentinel-app` application traffic under ADR-018
and are deliberately cache-eligible, unlike the eval harness's one call site
(`src.evals.evaluator.run_judge`) — guardrail verdicts are not the thing being
scored against a baseline the way eval-harness output is, so no
`cache={"no-cache": True}` override is set here.
"""

from __future__ import annotations

import json
from typing import Literal, Optional, TypedDict

from src.gateway.client_factory import get_chat_client


class GuardrailVerdict(TypedDict):
    verdict: Literal["safe", "unsafe"]
    reason: str
    category: Optional[str]


class GuardrailCheckError(RuntimeError):
    """Raised when the guardrail model's response is missing/invalid —
    never silently defaulted to "safe" (same "never silently default"
    discipline as DiagnoseError/RouterError/WritePostmortemError). A
    moderation hook that fails open on a malformed response would defeat
    the point of having one."""


_PROMPT_TEMPLATE = """You are a content moderation classifier (Llama Guard). \
Classify the following {direction} text flowing through an SRE incident \
response system. Respond with strict JSON only, no prose: \
{{"verdict": "safe" or "unsafe", "reason": <string>, "category": <taxonomy \
code string, e.g. "S1", or null>}}. "category" must be null when verdict is \
"safe", and a non-empty taxonomy code when verdict is "unsafe".

Text:
{text}
"""


def guardrail_check(text: str, direction: Literal["input", "output"]) -> GuardrailVerdict:
    """Moderate `text` flowing in the given `direction` through the graph.

    Calls Llama Guard 3-8B via the gateway (ADR-003/006/018/019) — never a
    direct provider SDK import. Raises `GuardrailCheckError` on a malformed
    response rather than silently treating it as safe.
    """
    client = get_chat_client(model="sentinel-guardrail")
    raw_response = client.invoke(_PROMPT_TEMPLATE.format(direction=direction, text=text))

    try:
        payload = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GuardrailCheckError(
            f"guardrail_check response was not valid JSON: {exc}"
        ) from exc

    verdict = payload.get("verdict")
    if verdict not in ("safe", "unsafe"):
        raise GuardrailCheckError(
            f"guardrail_check response had an invalid 'verdict': {verdict!r}"
        )

    reason = payload.get("reason")
    if not reason:
        raise GuardrailCheckError(
            f"guardrail_check response missing/empty 'reason': {reason!r}"
        )

    category = payload.get("category")
    if verdict == "safe" and category is not None:
        raise GuardrailCheckError(
            f"guardrail_check returned verdict='safe' with a non-null category: {category!r}"
        )
    if verdict == "unsafe" and not category:
        raise GuardrailCheckError(
            "guardrail_check returned verdict='unsafe' with no category"
        )

    return GuardrailVerdict(verdict=verdict, reason=reason, category=category)
