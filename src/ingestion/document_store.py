"""
Document store for the `documents(id, corpus, content, embedding, metadata)` table
(ADR-010, ADR-024).

**Architectural pattern — Repository:** `InMemoryDocumentStore` and
`PostgresDocumentStore` are two implementations of the same implicit
Repository interface (`upsert`, `count`, `rows_for_corpus`).  All callers
— `scripts/ingest_corpora.py` and the `retriever` node — work against this
interface and never reference `psycopg` or SQL directly.  Swapping backends
is transparent: `get_document_store(database_url)` selects the right
implementation at process startup (see the **Factory** note on that function
below), and call sites require zero changes.

**Architectural pattern — Factory:** `get_document_store(database_url)` is
the sole construction path for both implementations.  It encapsulates the
"which backend?" decision so no caller imports `PostgresDocumentStore` or
`InMemoryDocumentStore` by name — the same discipline as
`get_checkpointer()` and `get_chat_client()` elsewhere in the codebase.

ADR-024 (Production Readiness): `get_document_store(database_url)` returns a
`PostgresDocumentStore` backed by real psycopg+pgvector when the package is installed
and a `database_url` is provided, falling back to `InMemoryDocumentStore` (the
ADR-021 stdlib shim) otherwise.

Both implementations expose the same interface (`upsert`, `count`,
`rows_for_corpus`) so all callers — `scripts/ingest_corpora.py` and the
`retriever` node — work unchanged against either backend.

To initialise the real Postgres backend, run `infra/schema.sql` once against the
database before the first `make ingest`. The SQL schema creates the `documents`
table and the pgvector ivfflat index.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Real psycopg — used when installed (ADR-024).
try:
    import psycopg as _psycopg
    _PSYCOPG_AVAILABLE = True
except ImportError:
    _PSYCOPG_AVAILABLE = False


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
    """In-process fallback for the `documents` table (ADR-021). Dict-backed,
    keyed by content hash so `upsert` is idempotent on unchanged input.
    Used automatically when psycopg is not installed, and explicitly by tests."""

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


class PostgresDocumentStore:
    """Real document store backed by Postgres + pgvector (ADR-010, ADR-024).

    Requires `psycopg` and a running Postgres instance with the pgvector
    extension and `documents` table created via `infra/schema.sql`.

    `upsert` is idempotent (ON CONFLICT DO UPDATE) — safe to re-run
    `make ingest` against an already-populated database.
    """

    def __init__(self, conn) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        corpus: str,
        content: str,
        embedding: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DocumentRow:
        row_id = content_hash(content)
        self._conn.execute(
            """
            INSERT INTO documents (id, corpus, content, embedding, metadata)
            VALUES (%s, %s, %s, %s::vector, %s)
            ON CONFLICT (id) DO UPDATE
                SET embedding = EXCLUDED.embedding,
                    metadata  = EXCLUDED.metadata
            """,
            (row_id, corpus, content, embedding, json.dumps(metadata or {})),
        )
        self._conn.commit()
        return DocumentRow(
            id=row_id,
            corpus=corpus,
            content=content,
            embedding=embedding,
            metadata=metadata or {},
        )

    def count(self, corpus: Optional[str] = None) -> int:
        if corpus is None:
            row = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE corpus = %s", (corpus,)
            ).fetchone()
        return row[0] if row else 0

    def rows_for_corpus(self, corpus: str) -> List[DocumentRow]:
        rows = self._conn.execute(
            "SELECT id, corpus, content, embedding, metadata FROM documents "
            "WHERE corpus = %s",
            (corpus,),
        ).fetchall()
        return [
            DocumentRow(
                id=r[0],
                corpus=r[1],
                content=r[2],
                embedding=list(r[3]),
                metadata=json.loads(r[4]) if isinstance(r[4], str) else (r[4] or {}),
            )
            for r in rows
        ]


def get_document_store(database_url: Optional[str] = None):
    """Return the appropriate document store for the current environment.

    Returns a `PostgresDocumentStore` when psycopg is installed and
    `database_url` is provided; falls back to `InMemoryDocumentStore` otherwise.
    """
    if _PSYCOPG_AVAILABLE and database_url:
        conn = _psycopg.connect(database_url)
        return PostgresDocumentStore(conn)
    return InMemoryDocumentStore()


# Process-wide singleton used by ingest_corpora.py and the retriever node when
# no store is injected explicitly. On a machine with psycopg + DATABASE_URL this
# will become a PostgresDocumentStore; in the sandbox it stays InMemoryDocumentStore.
import os as _os
default_store = get_document_store(_os.environ.get("DATABASE_URL"))
