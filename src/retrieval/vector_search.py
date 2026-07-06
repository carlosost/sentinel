"""
Vector similarity search over the `documents` table (ADR-011, ADR-024).

ADR-024 (Production Readiness): `search()` now dispatches to either a real
pgvector cosine-distance SQL query (when the store is a `PostgresDocumentStore`)
or the original plain-Python cosine similarity (when the store is an
`InMemoryDocumentStore`). The dispatch is duck-typed on the store's class, so no
change is required in the `retriever` node.

The plain-Python path (O(n), no index) is correct for the sandbox's corpus sizes;
the pgvector path uses an ivfflat index and the `<=>` operator for production
performance. `EmbeddingDimensionMismatchError` is raised on both paths when the
query vector's dimension doesn't match the corpus (ADR-023 / Open Question #16).
"""

from __future__ import annotations

import json
import math
from typing import List, Tuple

from src.ingestion.document_store import (
    DocumentRow,
    InMemoryDocumentStore,
    PostgresDocumentStore,
)


class EmbeddingDimensionMismatchError(ValueError):
    """Raised when the query embedding's dimensionality does not match the corpus.

    Open Question #16 (ADR-023, Feature 15) resolution: deliberate fail-loud
    behavior — never silently truncate/pad a vector or return garbage results.
    Subclasses `ValueError` so existing `except ValueError` callers are unaffected.
    """


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 for a zero vector."""
    if len(a) != len(b):
        raise EmbeddingDimensionMismatchError(
            f"vector length mismatch: {len(a)} vs {len(b)} — embedding fallback "
            "likely answered with a different-dimension model than the corpus was "
            "ingested with (see ADR-023 / Open Question #16)."
        )
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _search_inmemory(
    store: InMemoryDocumentStore,
    corpus: str,
    query_embedding: List[float],
    k: int,
) -> List[Tuple[DocumentRow, float]]:
    """Plain-Python cosine similarity over the in-memory store (O(n), no index).
    Correct for sandbox corpus sizes; not a production performance claim."""
    candidates = store.rows_for_corpus(corpus)
    scored = [
        (row, cosine_similarity(query_embedding, row.embedding))
        for row in candidates
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]


def _search_postgres(
    store: PostgresDocumentStore,
    corpus: str,
    query_embedding: List[float],
    k: int,
) -> List[Tuple[DocumentRow, float]]:
    """pgvector cosine-distance query using the ivfflat index (ADR-011/ADR-024).

    Returns rows ordered by ascending cosine distance (`<=>`), which equals
    descending cosine similarity. Raises `EmbeddingDimensionMismatchError` when
    pgvector rejects the vector due to a dimension mismatch.
    """
    try:
        rows = store._conn.execute(
            """
            SELECT id, corpus, content, embedding, metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM documents
            WHERE corpus = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (query_embedding, corpus, query_embedding, k),
        ).fetchall()
    except Exception as exc:
        # pgvector raises a generic error on dimension mismatch; re-raise as
        # our named error so callers get a consistent exception type.
        if "different vector dimensions" in str(exc) or "vector" in str(exc).lower():
            raise EmbeddingDimensionMismatchError(
                f"pgvector dimension mismatch for corpus={corpus!r}: {exc} — "
                "re-run `make ingest` after swapping the embedding model."
            ) from exc
        raise
    return [
        (
            DocumentRow(
                id=r[0],
                corpus=r[1],
                content=r[2],
                embedding=list(r[3]),
                metadata=json.loads(r[4]) if isinstance(r[4], str) else (r[4] or {}),
            ),
            float(r[5]),
        )
        for r in rows
    ]


def search(
    store,
    corpus: str,
    query_embedding: List[float],
    *,
    k: int = 20,
) -> List[Tuple[DocumentRow, float]]:
    """Return up to `k` rows from `corpus`, ranked by descending cosine similarity.

    Dispatches to the pgvector SQL path when `store` is a `PostgresDocumentStore`,
    or the plain-Python path when it is an `InMemoryDocumentStore`. Fewer than `k`
    results is not an error (ADR-011 Gherkin scenario 1).
    """
    if isinstance(store, PostgresDocumentStore):
        return _search_postgres(store, corpus, query_embedding, k)
    return _search_inmemory(store, corpus, query_embedding, k)
