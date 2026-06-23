"""
`diagnose` node (ADR-013): produces a free-text root-cause diagnosis from
`state.reranked_docs` via a single structured-output call through
`client_factory.get_chat_client(...)`, plus a structured `diagnosis_confidence`
hedge signal honoring ADR-012's consequence that later nodes "must not assume
`relevance_grade >= 0.6` just because [diagnose] was reached."

`diagnosis_confidence` is set to `"low"` whenever `state.relevance_grade` is
below `RELEVANCE_THRESHOLD` (the same 0.6 cutoff `grade_documents` uses,
imported from there rather than redefined, so the two never drift) — this
covers both the "still low after retries were exhausted" case (ADR-012's
graceful-degradation path) and, trivially, the ordinary low-grade case.
`"high"` otherwise. This is a structured field, not a hedge folded into the
diagnosis text, so later nodes/tests can branch on it without parsing prose.

This feature scopes `diagnose` to the first-pass case only (the only path that
exists in the graph so far). `await_human_approval -(rejected)-> diagnose` and
`execute -(failure)-> diagnose` (roadmap items 9-10) will re-enter this node
with different context (a human's rejection note, or an execution failure) —
how `diagnose` should use that context is explicitly out of scope here, per
this feature's spec Conflict Check.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from src.gateway.client_factory import get_chat_client
from src.graph.nodes.grade_documents import RELEVANCE_THRESHOLD
from src.graph.state import IncidentState

CONFIDENCE_HIGH = "high"
CONFIDENCE_LOW = "low"

_PROMPT_TEMPLATE = """You are an SRE incident diagnosis assistant. Read the \
incident and the retrieved context below and write a concise root-cause \
diagnosis. Respond with strict JSON only, no prose: {{"diagnosis": <string>}}.

Incident:
{query}

Retrieved context:
{context}
"""


class DiagnoseError(RuntimeError):
    """Raised when the diagnose call's response is missing/invalid — never
    silently defaulted to an empty diagnosis (same discipline as
    RouterError/RetrieverError/GradeDocumentsError)."""


def _build_prompt(query: str, docs: List[dict]) -> str:
    context = "\n\n".join(doc["content"] for doc in docs) or "(no documents retrieved)"
    return _PROMPT_TEMPLATE.format(query=query, context=context)


def diagnose(state: IncidentState) -> Dict[str, Any]:
    query = state.get("current_query") or state["raw_alert"]
    docs = state.get("reranked_docs") or []

    client = get_chat_client(model="sentinel-diagnose")
    raw_response = client.invoke(_build_prompt(query, docs))

    try:
        payload = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DiagnoseError(f"diagnose response was not valid JSON: {exc}") from exc

    diagnosis_text = payload.get("diagnosis")
    if not diagnosis_text:
        raise DiagnoseError(f"diagnose response missing/empty 'diagnosis': {diagnosis_text!r}")

    grade = state.get("relevance_grade")
    confidence = CONFIDENCE_LOW if (grade is None or grade < RELEVANCE_THRESHOLD) else CONFIDENCE_HIGH

    return {"diagnosis": diagnosis_text, "diagnosis_confidence": confidence}
