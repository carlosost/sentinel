"""
Stdlib stand-in for the Postgres+pgvector `documents` table ADR-010 specifies
(`documents(id, corpus, content, embedding, metadata)`).

SANDBOX NOTE (ADR-021 addendum, Feature 04): this dev sandbox has neither
`psycopg2` (no PyPI egress) nor a live Postgres instance to connect to, so the
real `documents` table cannot be exercised here. `InMemoryDocumentStore` below
is a plain-dict stand-in that preserves the table's row shape and its one
load-bearing behavior for this feature — idempotent upsert keyed on a content
hash, so re-running ingestion on unchanged source files does not duplicate
rows (ADR-010's Gherkin scenario 2).

This shim is intentionally narrow: it does NOT implement the cosine-similarity
query the real `retriever` node (roadmap item 5 / Feature 05) will need —
that's a SQL-level operation this stdlib stand-in has no way to represent
faithfully, so Feature 05 is explicitly excluded from this swap and will need
its own decision once real pgvector access exists. Open Question #15 tracks
swapping this whole module for real psycopg2/pgvector.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def content_hash(content: str) -> str:
    """Stable content-addressed row key — the upsert/idempotency mechanism."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class DocumentRow:
    id: str
    corpus: str
    content: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


class InMemoryDocumentStore:
    """Dict-backed stand-in for the `documents` table. Keyed by content hash
    so `upsert` is idempotent on unchanged input."""

    def __init__(self) -> None:
        self._rows: Dict[str, DocumentRow] = {}

    def upsert(
        self,
        *,
        corpus: str,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DocumentRow:
        row_id = content_hash(content)
        row = DocumentRow(
            id=row_id,
            corpus=corpus,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
        )
        self._rows[row_id] = row
        return row

    def count(self, corpus: Optional[str] = None) -> int:
        if corpus is None:
            return len(self._rows)
        return sum(1 for row in self._rows.values() if row.corpus == corpus)

    def rows_for_corpus(self, corpus: str) -> List[DocumentRow]:
        return [row for row in self._rows.values() if row.corpus == corpus]


# Process-wide singleton — the in-sandbox stand-in for "the one Postgres
# `documents` table every node talks to" (ADR-021 addendum, Feature 05).
# `scripts/ingest_corpora.py` writes here by default; `retriever`
# (`src/graph/nodes/retriever.py`) reads from here by default. Tests construct
# their own `InMemoryDocumentStore()` instances instead of touching this
# singleton, so test runs never interfere with each other.
default_store = InMemoryDocumentStore()
