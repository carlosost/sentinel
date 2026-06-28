"""
Stdlib stand-in for the pgvector cosine-similarity query ADR-011 specifies for
`retriever` (`SELECT ... WHERE corpus = %s ORDER BY embedding <=> %s LIMIT %s`).

SANDBOX NOTE (ADR-021 addendum, Feature 05): `src/ingestion/document_store.py`'s
docstring (Feature 04) explicitly deferred this — `InMemoryDocumentStore` stores
rows but does not know how to rank them. This module is that deferred decision:
plain-Python cosine similarity over the in-memory rows, filtered by corpus. It
is a stand-in for pgvector's `<=>` operator, not a faithful reproduction of it
(no index, no approximate search, O(n) per query) — fine for this sandbox's
corpus sizes (a handful of synthetic documents per corpus), not a claim about
production behavior. Open Question #15 tracks swapping this for a real
psycopg2/pgvector query.
"""

from __future__ import annotations

import math
from typing import List, Tuple

from src.ingestion.document_store import DocumentRow, InMemoryDocumentStore


class EmbeddingDimensionMismatchError(ValueError):
    """Raised by `cosine_similarity`/`search` when the query embedding's
    dimensionality does not match the corpus rows it is being compared
    against.

    Open Question #16 (ADR-023, Feature 15) resolution: this is the
    deliberate, named failure mode for a query embedding produced by a
    different model than the one that embedded the corpus — most likely
    `sentinel-embedding-fallback` (Ollama `bge-m3`, 1024-dim) answering a
    query while `corpora/` was ingested via the primary
    (`text-embedding-3-small`, 1536-dim; see `scripts/ingest_corpora.py`,
    which always calls `embedding_model="sentinel-embedding"`, never the
    `-fallback` alias). The decision (Option B over a per-dimension index):
    fail loudly and let the `retriever` node raise rather than silently
    truncating/padding a vector or returning similarity-ranked garbage. A
    per-dimension index (Option A) was rejected as disproportionate for v1 —
    this fallback only fires during a full OpenAI-embeddings outage, not
    everyday traffic, so a hard, visible failure during a rare total outage
    is an accepted tradeoff, not a gap. Subclasses `ValueError` so any
    existing `except ValueError` callers are unaffected."""


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity in [-1, 1] (1 = identical direction). Returns 0.0 for a
    zero vector rather than dividing by zero — an edge case pgvector itself
    would reject differently, but one this stand-in must not crash on."""
    if len(a) != len(b):
        raise EmbeddingDimensionMismatchError(
            f"vector length mismatch: {len(a)} vs {len(b)} — if this came from "
            "a real query/corpus pair, the embedding fallback likely answered "
            "with a different-dimension model than the corpus was ingested "
            "with (see Open Question #16 / ADR-023)."
        )

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def search(
    store: InMemoryDocumentStore,
    corpus: str,
    query_embedding: List[float],
    *,
    k: int = 20,
) -> List[Tuple[DocumentRow, float]]:
    """Return up to `k` rows from `corpus`, ranked by descending cosine
    similarity to `query_embedding`. Fewer than `k` results is not an error —
    it means the corpus has fewer than `k` rows (ADR-011's Gherkin scenario 1)."""
    candidates = store.rows_for_corpus(corpus)
    scored = [(row, cosine_similarity(query_embedding, row.embedding)) for row in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]
