"""
`grade_documents` node (ADR-012): scores `state.reranked_docs` for relevance via
a single structured-output call through `client_factory.get_chat_client(...)`,
returning `{"relevance_grade": <float 0.0-1.0>, "reformulated_query": <string
or null>}`. This is the graph's first real cycle — see this feature's Conflict
Check and ADR-012 for why a linear chain or single conditional branch can't
express "retry up to 2 times then give up gracefully."

Routing is decided separately by `grade_documents_route` (the path function
passed to `add_conditional_edges`), per the same node/router split
`guardrail_input`/`guardrail_input_route` established in Feature 03.

**Retry-counting semantics (a deliberate, documented resolution of an ambiguity
the original Gherkin's wording left open):** `retry_count` counts the number of
*low-relevance gradings seen so far*, incremented every time `relevance_grade`
is below threshold — whether or not a retry is actually taken — not the number
of retries taken. A path function deciding "router vs diagnose" from final
state alone cannot otherwise distinguish "just used the last allowed retry"
from "already had no retries left before this call," since both states would
otherwise converge on the same `retry_count` value. Counting every low-relevance
grading (monotonically increasing, never reset) removes that ambiguity:
`retry_count <= MAX_RETRIES` is retried, anything past that gives up — and the
boundary trace (`MAX_RETRIES=2`: gradings at retry_count 1 and 2 retry, grading
at retry_count 3 gives up) matches ADR-012's "capped at 2 retries" exactly.

Threshold (`relevance_grade < 0.6` = low relevance) is a placeholder pending
eval-driven tuning (ADR-012, tracked as a new Open Question) — not asserted as
correct here.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from src.gateway.client_factory import get_chat_client
from src.graph.state import IncidentState

RELEVANCE_THRESHOLD = 0.6
MAX_RETRIES = 2

ROUTE_RETRY = "router"
ROUTE_PROCEED = "diagnose"

_PROMPT_TEMPLATE = """You are grading whether the retrieved context below is \
relevant enough to diagnose the incident. Respond with strict JSON only, no \
prose: {{"relevance_grade": <float 0.0-1.0>, "reformulated_query": <string or \
null, required if relevance_grade < {threshold}>}}.

Incident:
{query}

Retrieved context:
{context}
"""


class GradeDocumentsError(RuntimeError):
    """Raised when the grading call's response is missing/invalid, or when a
    retry is due but the response didn't supply a reformulated_query — never
    silently defaulted to a passing grade or an unchanged query (same
    discipline as RouterError/RetrieverError)."""


def _build_prompt(query: str, docs: List[dict]) -> str:
    context = "\n\n".join(doc["content"] for doc in docs) or "(no documents retrieved)"
    return _PROMPT_TEMPLATE.format(threshold=RELEVANCE_THRESHOLD, query=query, context=context)


def grade_documents(state: IncidentState) -> Dict[str, Any]:
    query = state.get("current_query") or state["raw_alert"]
    docs = state.get("reranked_docs") or []

    client = get_chat_client(model="sentinel-grader")
    raw_response = client.invoke(_build_prompt(query, docs))

    try:
        payload = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GradeDocumentsError(
            f"grade_documents response was not valid JSON: {exc}"
        ) from exc

    grade = payload.get("relevance_grade")
    if not isinstance(grade, (int, float)):
        raise GradeDocumentsError(
            f"grade_documents response missing/invalid 'relevance_grade': {grade!r}"
        )

    update: Dict[str, Any] = {"relevance_grade": float(grade)}

    if grade < RELEVANCE_THRESHOLD:
        low_relevance_count = state.get("retry_count", 0) + 1
        update["retry_count"] = low_relevance_count
        if low_relevance_count <= MAX_RETRIES:
            reformulated = payload.get("reformulated_query")
            if not reformulated:
                raise GradeDocumentsError(
                    "grade_documents returned relevance_grade below threshold and "
                    "a retry is due, but no reformulated_query was supplied "
                    "(required when retrying, ADR-012)."
                )
            update["current_query"] = reformulated

    return update


def grade_documents_route(state: IncidentState) -> str:
    """Path function for the conditional edge out of `grade_documents`. Low
    relevance with a retry still within budget loops back to `router`;
    everything else (high relevance, or the retry budget exhausted — ADR-012's
    graceful degradation) proceeds to `diagnose`."""
    grade = state["relevance_grade"]
    retry_count = state.get("retry_count", 0)
    if grade < RELEVANCE_THRESHOLD and retry_count <= MAX_RETRIES:
        return ROUTE_RETRY
    return ROUTE_PROCEED
