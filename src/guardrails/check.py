"""
Guardrail moderation hook (ADR-004, ADR-007, ADR-019, ADR-023-Phase5).

v1 (Feature 01) stubbed this to always return "safe". Feature 13 (ADR-019)
replaced the body with a real Llama Guard call. ADR-023 Phase 5 (2026-07-06)
migrated the primary from TogetherAI to a local Ollama-served Llama Guard 3.

Output format alignment (ADR-023-Phase5): Llama Guard 3 is fine-tuned to
produce a native two-line format — `safe` or `unsafe\nS1,S3` — not arbitrary
JSON. `guardrail_check()` now uses a prompt that elicits this native format
and parses it via `_parse_native()`. A `_parse_json()` fallback handles any
model that still returns the old JSON format (including the
`sentinel-guardrail-fallback` via `openai/omni-moderation-latest`), so the
function works correctly with either model. JSON is tried only when the native
parse fails.

`GuardrailVerdict`'s shape is unchanged (ADR-019): `verdict`, `reason`,
`category`. `GuardrailCheckError` is raised when neither parser succeeds —
the "never silently default to safe" invariant is preserved.
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
    """Raised when the guardrail model's response is unparseable — never
    silently defaulted to 'safe' (same 'never silently default' discipline
    as DiagnoseError/RouterError/WritePostmortemError). A moderation hook that
    fails open on a malformed response defeats the point of having one."""


# ---------------------------------------------------------------------------
# Llama Guard 3 category taxonomy (S1–S13)
# ---------------------------------------------------------------------------

_S_CODE_LABELS: dict[str, str] = {
    "S1": "Violent Crimes",
    "S2": "Non-Violent Crimes",
    "S3": "Sex-Related Crimes",
    "S4": "Child Sexual Exploitation",
    "S5": "Defamation",
    "S6": "Specialized Advice",
    "S7": "Privacy",
    "S8": "Intellectual Property",
    "S9": "Indiscriminate Weapons",
    "S10": "Hate",
    "S11": "Suicide & Self-Harm",
    "S12": "Sexual Content",
    "S13": "Elections",
}

# Maps the direction argument to the conversation role label Llama Guard 3 uses
# in its training data — "User" for incoming text, "Agent" for outgoing actions.
_DIRECTION_LABEL: dict[str, str] = {
    "input": "User",
    "output": "Agent",
}

# Llama Guard 3 native prompt: elicits the two-line 'safe'/'unsafe\nS1' format
# the model was fine-tuned on. Providing the category taxonomy explicitly
# inside the prompt is the approach recommended in the Meta paper and matches
# Llama Guard 3's own system-prompt template.
_LLAMA_GUARD_TEMPLATE = """Task: Check if there is unsafe content in the '{direction_label}' messages in the conversation according to our safety policy.

<BEGIN UNSAFE CONTENT CATEGORIES>
S1: Violent Crimes.
S2: Non-Violent Crimes.
S3: Sex-Related Crimes.
S4: Child Sexual Exploitation.
S5: Defamation.
S6: Specialized Advice (medical, legal, financial without disclaimer).
S7: Privacy (unauthorized disclosure of personal information).
S8: Intellectual Property.
S9: Indiscriminate Weapons (CBRN, mass-casualty content).
S10: Hate (derogatory content targeting protected groups).
S11: Suicide & Self-Harm.
S12: Sexual Content (explicit).
S13: Elections (voter suppression, election interference).
<END UNSAFE CONTENT CATEGORIES>

<BEGIN CONVERSATION>
{direction_label}: {text}
<END CONVERSATION>

Provide your safety assessment for the above conversation:
- First line must read 'safe' or 'unsafe'.
- If 'unsafe', a second line must include a comma-separated list of violated categories (e.g. 'S1,S3')."""


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def _parse_native(response: str) -> Optional[GuardrailVerdict]:
    """Parse Llama Guard 3's native output format: 'safe' or 'unsafe\\nS1,S3'.

    Returns a `GuardrailVerdict` dict on success, `None` when the response
    doesn't match the native format (signals the caller to try JSON parsing).
    """
    lines = [line.strip() for line in response.strip().splitlines() if line.strip()]
    if not lines:
        return None

    first = lines[0].lower()

    if first == "safe":
        return GuardrailVerdict(
            verdict="safe",
            reason="Content classified as safe by Llama Guard.",
            category=None,
        )

    if first == "unsafe":
        if len(lines) < 2:
            # "unsafe" with no category line — malformed native response.
            return None
        codes = [c.strip().upper() for c in lines[1].split(",") if c.strip()]
        primary_code = codes[0] if codes else None
        if not primary_code:
            return None
        labels = ", ".join(_S_CODE_LABELS.get(c, c) for c in codes)
        return GuardrailVerdict(
            verdict="unsafe",
            reason=f"Violated categories: {labels}",
            category=primary_code,
        )

    return None  # first line is neither 'safe' nor 'unsafe' — not native format


def _parse_json(response: str) -> Optional[dict]:
    """Parse the legacy JSON format returned by non-Llama-Guard models.

    Returns the parsed dict on success, `None` on JSON decode failure.
    Used as fallback when `_parse_native` returns None.
    """
    try:
        return json.loads(response)
    except (TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def guardrail_check(text: str, direction: Literal["input", "output"]) -> GuardrailVerdict:
    """Moderate `text` flowing in the given `direction` through the graph.

    Calls Llama Guard 3-8B (local Ollama) or the configured fallback via the
    gateway (ADR-003/006/018/019/023-Phase5) — never a direct provider SDK
    import. Raises `GuardrailCheckError` on an unparseable response rather
    than silently treating it as safe.

    Response parsing priority:
    1. Native Llama Guard format (`safe` / `unsafe\\nS1,S3`)
    2. JSON format (`{"verdict": ..., "reason": ..., "category": ...}`)
    3. GuardrailCheckError — neither parser succeeded
    """
    direction_label = _DIRECTION_LABEL[direction]
    client = get_chat_client(model="sentinel-guardrail")
    raw_response = client.invoke(
        _LLAMA_GUARD_TEMPLATE.format(direction_label=direction_label, text=text)
    )

    # Try native format first, then JSON fallback.
    payload = _parse_native(raw_response) or _parse_json(raw_response)

    if payload is None:
        raise GuardrailCheckError(
            f"guardrail_check response was not parseable as native Llama Guard "
            f"format or JSON: {raw_response!r}"
        )

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
