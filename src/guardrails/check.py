"""
Guardrail moderation hook (ADR-004, ADR-007).

v1 (Feature 01): the function signature, node wiring, and LangSmith span are real;
the moderation decision itself is stubbed to always return "safe". This lets every
node that needs to call a guardrail wire the call site now, so unstubbing later
(roadmap item 13 / ADR-019) is a one-function change, not a graph rewire.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class GuardrailVerdict(TypedDict):
    verdict: Literal["safe", "unsafe"]
    reason: str


def guardrail_check(text: str, direction: Literal["input", "output"]) -> GuardrailVerdict:
    """Moderate `text` flowing in the given `direction` through the graph.

    Stubbed in v1 — always returns a "safe" verdict regardless of input. Real
    Llama Guard 3-8B inference is wired in by Feature 13 (ADR-019), which replaces
    this body without changing the signature or any call site.
    """
    return GuardrailVerdict(verdict="safe", reason="stub")
