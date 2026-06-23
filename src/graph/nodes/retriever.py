"""
`retriever` node (ADR-011): pgvector cosine-similarity search at top-k=20
against the corpus `router` selected (`state.route`), via
`client_factory.get_embedding_client(...)`. Writing `state.retrieved_docs` is
the node's only state mutation — re-ranking is `reranker`'s job (this same
feature, next node in the chain), not this one's.

Reads `state.current_query`, falling back to `state.raw_alert` when unset
(ADR-012, Feature 06) — same forward note as `router`'s, now resolved: a
self-RAG retry loop re-entering `retriever` via `router` embeds the
reformulated query, not the original alert text.

ADR-020 (Feature 14): the embedding call gains a second, config-flag-gated
code path. `EMBEDDING_MODEL_VARIANT=finetuned` loads the locally fine-tuned
model (`src.embeddings.finetuned_embeddings`, outside the gateway by design,
the third instance of that precedent after the reranker/ADR-011 and tool
execution/ADR-016) instead of calling `client_factory.get_embedding_client`.
Default (`base`, or unset) is unchanged — gateway-routed as before. Either
path produces the same `retrieved_docs` shape (ADR-011), so no downstream
node is affected by which variant ran.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.embeddings.finetuned_embeddings import get_finetuned_embedding_model
from src.gateway.client_factory import get_embedding_client
from src.graph.state import IncidentState
from src.ingestion.document_store import InMemoryDocumentStore, default_store
from src.retrieval.vector_search import search

TOP_K = 20

EMBEDDING_MODEL_VARIANT_ENV = "EMBEDDING_MODEL_VARIANT"


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
    query = state.get("current_query") or state["raw_alert"]

    if os.environ.get(EMBEDDING_MODEL_VARIANT_ENV) == "finetuned":
        model = get_finetuned_embedding_model()
        query_embedding = model.embed_documents([query])[0]
    else:
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
