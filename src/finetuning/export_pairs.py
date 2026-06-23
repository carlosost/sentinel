"""Contrastive pair export from `retriever`/`reranker` LangSmith spans (ADR-020).

Corrects Pillar 6's original prose: contrastive pairs come from the
`retriever`/`reranker` nodes' real per-document cross-encoder `score`
(ADR-011), never from `grade_documents` — that node only ever emits one
*aggregate* `relevance_grade` for the whole batch (ADR-012), so there was
nothing per-document to export from it as Pillar 6's first draft claimed.
"""

from __future__ import annotations

from typing import Any, Dict, List


class ExportPairsError(ValueError):
    """Raised when a span is missing a required field or has no negative
    example available — a malformed/incomplete span is never silently
    skipped."""


def build_finetune_pairs(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build one `{"query", "positive", "negative"}` contrastive pair per span.

    `positive` is `reranked_docs[0]` — the highest cross-encoder `score`
    (ADR-011's reranker node already sorts `reranked_docs` descending).
    `negative` is the first `retrieved_docs` entry whose `id` did not survive
    re-ranking into the top-k — a document the cross-encoder demoted, never a
    field read from a `grade_documents` span (ADR-020's corrected source).
    """
    pairs: List[Dict[str, Any]] = []
    for span in spans:
        query = span.get("query")
        if not query:
            raise ExportPairsError("span is missing a non-empty 'query'")

        reranked = span.get("reranked_docs") or []
        if not reranked:
            raise ExportPairsError(f"span for query {query!r} has no reranked_docs")

        retrieved = span.get("retrieved_docs") or []
        reranked_ids = {doc["id"] for doc in reranked}
        negative_candidates = [doc for doc in retrieved if doc["id"] not in reranked_ids]
        if not negative_candidates:
            raise ExportPairsError(
                f"span for query {query!r} has no retrieved_docs outside the "
                "reranked top-k to use as a negative example"
            )

        pairs.append(
            {
                "query": query,
                "positive": reranked[0],
                "negative": negative_candidates[0],
            }
        )
    return pairs
