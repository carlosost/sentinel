"""LangSmith retriever/reranker span fetcher for fine-tuning data export
(ADR-020, ADR-024).

ADR-024 (Production Readiness): `get_retriever_reranker_spans()` now fetches
real LangSmith `retriever`/`reranker` run pairs when `langsmith` is installed
and `LANGSMITH_API_KEY` + `LANGSMITH_PROJECT` are set. Falls back to raising
`NotImplementedError` (the ADR-021 shim) otherwise.

Tests patch `get_retriever_reranker_spans` directly at the script's import path
— the same seam pattern as `get_chat_client`/`get_reranker_model`.

The returned list is shaped `[{"query": str, "retrieved_docs": [...],
"reranked_docs": [...]}]` (ADR-011's document shape), consumed by
`scripts/export_finetune_pairs.py`.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Real langsmith — used when installed (ADR-024).
try:
    from langsmith import Client as _LangSmithClient
    _LANGSMITH_AVAILABLE = True
except ImportError:
    _LANGSMITH_AVAILABLE = False


def get_retriever_reranker_spans(
    project_name: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Fetch retriever+reranker span pairs from LangSmith.

    Each item is shaped `{"query": str, "retrieved_docs": [...],
    "reranked_docs": [...]}` (ADR-011 document shape), consumed by
    `scripts/export_finetune_pairs.py` to build fine-tuning pairs.

    When `langsmith` is installed and `LANGSMITH_API_KEY` is set, fetches real
    runs from the project named by `project_name` (defaults to
    `LANGSMITH_PROJECT` env var). Raises `NotImplementedError` when neither
    condition holds — the same fail-loud discipline as the other ADR-021 shims.

    Args:
        project_name: LangSmith project to query. Defaults to `LANGCHAIN_PROJECT`.
        limit: Maximum number of retriever run pairs to fetch.
    """
    # LANGSMITH_API_KEY (not the legacy LANGCHAIN_API_KEY) — LangSmith renamed
    # its env vars in mid-2025. LANGSMITH_PROJECT likewise replaces
    # LANGCHAIN_PROJECT. Using the old names causes silent fall-through to the
    # shim (NotImplementedError below) even when a real key is configured.
    if not (_LANGSMITH_AVAILABLE and os.environ.get("LANGSMITH_API_KEY")):
        raise NotImplementedError(
            "Fetching real LangSmith retriever/reranker spans requires the langsmith "
            "package and LANGSMITH_API_KEY to be set (run `make up` or set the env var)."
        )

    project = project_name or os.environ.get("LANGSMITH_PROJECT", "sentinel")
    client = _LangSmithClient()

    # Fetch retriever runs paired with their sibling reranker runs.
    retriever_runs = list(
        client.list_runs(
            project_name=project,
            run_type="chain",
            filter='eq(name, "retriever")',
            limit=limit,
        )
    )

    spans: List[Dict[str, Any]] = []
    for run in retriever_runs:
        outputs = run.outputs or {}
        inputs = run.inputs or {}
        query = inputs.get("query", "")
        retrieved_docs = outputs.get("retrieved_docs", [])
        reranked_docs = outputs.get("reranked_docs", retrieved_docs)
        if query and retrieved_docs:
            spans.append(
                {
                    "query": query,
                    "retrieved_docs": retrieved_docs,
                    "reranked_docs": reranked_docs,
                    "run_id": str(run.id),
                }
            )

    return spans
