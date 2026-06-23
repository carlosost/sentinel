"""
`reranker` node (ADR-011): `bge-reranker-base` cross-encoder re-ranking of
`state.retrieved_docs` (top-k=20) down to `state.reranked_docs` (top-k=5).
Confirmed by ADR-011 as outside the gateway contract — this node must never
call `client_factory.get_chat_client`/`get_embedding_client`; it only imports
`src.reranking.cross_encoder`, which has no dependency on the gateway module at
all (see that module's docstring).

Each output entry overwrites `score` with the cross-encoder score rather than
keeping the vector-similarity score alongside it — ADR-011 decided only one
ranking is authoritative at a time, so `grade_documents` (Feature 06) always
reads one unambiguous `score` field regardless of which node produced it.

Reads `state.current_query`, falling back to `state.raw_alert` when unset
(ADR-012, Feature 06), same as `router`/`retriever` — a self-RAG retry scores
candidates against the reformulated query, not the original alert text.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.graph.state import IncidentState
from src.reranking.cross_encoder import get_reranker_model

TOP_K = 5


def reranker(state: IncidentState) -> Dict[str, Any]:
    docs: List[dict] = state.get("retrieved_docs") or []
    if not docs:
        return {"reranked_docs": []}

    query = state.get("current_query") or state["raw_alert"]
    model = get_reranker_model()
    pairs = [(query, doc["content"]) for doc in docs]
    scores = model.predict(pairs)

    reranked = []
    for doc, score in zip(docs, scores):
        new_doc = dict(doc)
        new_doc["score"] = float(score)
        reranked.append(new_doc)

    reranked.sort(key=lambda d: d["score"], reverse=True)
    return {"reranked_docs": reranked[:TOP_K]}
