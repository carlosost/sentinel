"""Stdlib stand-in for fetching real LangSmith `retriever`/`reranker` spans
(ADR-020).

ADR-021 established that this sandbox has no PyPI egress, so the real
`langsmith` package (and a real running project to fetch spans from) is not
available here. This module is that same substitution, scoped to exactly what
`scripts/export_finetune_pairs.py` needs: a list of per-query span dicts
carrying both the pre-rerank `retrieved_docs` and post-rerank `reranked_docs`
shapes ADR-011 already pinned.

Swap for a real `langsmith.Client().list_runs(...)` call once this sandbox has
real package access — see Open Question #15. Tests patch
`get_retriever_reranker_spans` directly, the same seam pattern as
`get_chat_client`/`get_reranker_model`.
"""

from __future__ import annotations

from typing import Any, Dict, List


def get_retriever_reranker_spans() -> List[Dict[str, Any]]:
    """Fetch retriever+reranker span pairs for every query run through the graph
    recently, each shaped `{"query": str, "retrieved_docs": [...], "reranked_docs":
    [...]}` (ADR-011's document shape). Real inference requires the `langsmith`
    package and a configured project with real traces — neither available in
    this sandbox (Open Question #15)."""
    raise NotImplementedError(
        "Fetching real LangSmith retriever/reranker spans requires the langsmith "
        "package and a configured project with real traces, not available in "
        "this sandbox (Open Question #15)."
    )
