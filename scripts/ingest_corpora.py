#!/usr/bin/env python3
"""`make ingest` entry point (ADR-010, ADR-024): idempotently ingest
corpora/{runbooks,postmortems,infra_code_docs}/*.md into the `documents`
store.

Runs inside Docker via `make ingest` (which calls `$(COMPOSE) run --rm app
ingest`) so DATABASE_URL and LITELLM_PROXY_URL are automatically available
from docker-compose.yml. Uses `get_document_store(DATABASE_URL)` — a real
PostgresDocumentStore when DATABASE_URL is set, InMemoryDocumentStore as
fallback. Ingestion mechanics (corpus tagging, idempotent upsert) are tested
independently in tests/ingestion/test_ingest_corpora.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import os  # noqa: E402

from src.gateway.client_factory import GatewayConfigError, get_embedding_client  # noqa: E402
from src.ingestion.document_store import get_document_store  # noqa: E402

CORPORA_ROOT = REPO_ROOT / "corpora"
CORPUS_NAMES = ("runbooks", "postmortems", "infra_code_docs")


def _load_corpus_files(corpus: str, root: Path) -> List[Path]:
    corpus_dir = root / corpus
    if not corpus_dir.is_dir():
        return []
    return sorted(corpus_dir.glob("*.md"))


def ingest_corpus(
    corpus: str,
    store,
    *,
    root: Path = CORPORA_ROOT,
    embedding_model: str = "sentinel-embedding",
) -> int:
    """Ingest every markdown file in corpora/<corpus>/ into `store`.

    Idempotent: re-running with unchanged files upserts the same
    content-hash-keyed rows rather than duplicating them (ADR-010's Gherkin
    scenario 2). Returns the number of files processed (not necessarily the
    number of *new* rows).
    """
    files = _load_corpus_files(corpus, root)
    if not files:
        return 0

    client = get_embedding_client(model=embedding_model)
    for path in files:
        content = path.read_text(encoding="utf-8")
        embedding = client.embed_documents([content])[0]
        store.upsert(
            corpus=corpus,
            content=content,
            embedding=embedding,
            metadata={"source": str(path)},
        )
    return len(files)


def ingest_all(
    store, *, root: Path = CORPORA_ROOT
) -> Dict[str, int]:
    return {corpus: ingest_corpus(corpus, store, root=root) for corpus in CORPUS_NAMES}


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    store = get_document_store(database_url)
    backend = "PostgresDocumentStore" if database_url else "InMemoryDocumentStore (no DATABASE_URL set)"
    print(f"Sentinel corpus ingestion — {CORPORA_ROOT.relative_to(REPO_ROOT)}")
    print(f"  Store backend: {backend}")

    try:
        counts = ingest_all(store)
    except (GatewayConfigError, NotImplementedError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        print(
            "Real ingestion requires a configured LiteLLM proxy and "
            "langchain_openai, neither available in this sandbox (Open "
            "Question #15). Ingestion mechanics are verified instead via "
            "tests/ingestion/test_ingest_corpora.py (mocked embedding "
            "client).",
            file=sys.stderr,
        )
        return 1

    for corpus, n in counts.items():
        print(f"  {corpus}: {n} files processed, {store.count(corpus)} rows in store")
    return 0


if __name__ == "__main__":
    sys.exit(main())
