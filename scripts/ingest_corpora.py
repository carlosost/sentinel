#!/usr/bin/env python3
"""`make ingest` entry point (ADR-010): idempotently ingest
corpora/{runbooks,postmortems,infra_code_docs}/*.md into the `documents`
store.

SANDBOX NOTE (ADR-021 addendum, Feature 04): the store this script writes to
is `src/ingestion/document_store.py`'s stdlib `InMemoryDocumentStore` shim,
not real pgvector (see that module's docstring), and embeddings come from
`client_factory.get_embedding_client(...)`, which itself requires
`LITELLM_PROXY_URL` to be set (ADR-003) and whose stub client's
`.embed_documents()` raises `NotImplementedError` even once that's set (Open
Question #15). Running this script directly in this sandbox will therefore
fail — either at client construction (`GatewayConfigError`, no proxy
configured here) or at the embedding call itself — and that is expected and
reported clearly below, not silently worked around. Ingestion *mechanics*
(corpus tagging, idempotent upsert) are proven instead against a mocked
embedding client in tests/ingestion/test_ingest_corpora.py, the same
Deterministic Tier pattern used for every other gateway-backed call in this
project (e.g. Feature 02's test_gateway_compliance.py).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.gateway.client_factory import GatewayConfigError, get_embedding_client  # noqa: E402
from src.ingestion.document_store import InMemoryDocumentStore  # noqa: E402

CORPORA_ROOT = REPO_ROOT / "corpora"
CORPUS_NAMES = ("runbooks", "postmortems", "infra_code_docs")


def _load_corpus_files(corpus: str, root: Path) -> List[Path]:
    corpus_dir = root / corpus
    if not corpus_dir.is_dir():
        return []
    return sorted(corpus_dir.glob("*.md"))


def ingest_corpus(
    corpus: str,
    store: InMemoryDocumentStore,
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
    store: InMemoryDocumentStore, *, root: Path = CORPORA_ROOT
) -> Dict[str, int]:
    return {corpus: ingest_corpus(corpus, store, root=root) for corpus in CORPUS_NAMES}


def main() -> int:
    store = InMemoryDocumentStore()
    print(f"Sentinel corpus ingestion — {CORPORA_ROOT.relative_to(REPO_ROOT)}")

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
