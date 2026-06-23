"""
`retriever` node (ADR-011): pgvector cosine-similarity search at top-k=20
against the corpus `router` selected (`state.route`), via
`client_factory.get_embedding_client(...)`. Writing `state.retrieved_docs` is
the node's only state mutation — re-ranking is `reranker`'s job (this same
feature, next node in the chain), not this one's.

v1 reads `state["raw_alert"]` directly. ADR-012 (Feature 06) introduces
`state.current_query` (init = raw_alert, overwritten on self-RAG retry); once
that field exists, this node must read it (falling back to raw_alert) instead
of raw_alert directly — same forward note as `router`'s (see this feature's
"Forward Note" in memory/features/feature-05-retriever-reranker-nodes.md).
Nothing here asserts current_query already exists.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.gateway.client_factory import get_embedding_client
from src.graph.state import IncidentState
from src.ingestion.document_store import InMemoryDocumentStore, default_store
from src.retrieval.vector_search import search

TOP_K = 20


class RetrieverError(RuntimeError):
    """Raised when `retriever` runs before `router` has set `state.route` —
    never silently falls back to a default corpus (same discipline as
    `RouterError`)."""


def retriever(
    state: IncidentState,
    *,
    store: Optional[InMemoryDocumentStore] = None,
) -> Dict[str, Any]:
    corpus = state.get("route")
    if corpus is None:
        raise RetrieverError(
            "retriever requires state.route to be set — router must run first."
        )

    active_store = store if store is not None else default_store
    query = state["raw_alert"]

    client = get_embedding_client(model="sentinel-embedding")
    query_embedding = client.embed_documents([query])[0]

    results = search(active_store, corpus, query_embedding, k=TOP_K)
    retrieved_docs = [
        {
            "id": row.id,
            "corpus": row.corpus,
            "content": row.content,
            "source": row.metadata.get("source", ""),
            "score": score,
        }
        for row, score in results
    ]
    return {"retrieved_docs": retrieved_docs}
