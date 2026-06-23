"""Deterministic Tier — ingestion mechanics (corpus tagging, idempotency)
only; embedding content/quality is never asserted here. The embedding client
is mocked, same gateway-mocking pattern as Feature 02's
test_gateway_compliance.py (ADR-010's Gherkin scenarios 1 and 2)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.ingest_corpora import ingest_all, ingest_corpus
from src.ingestion.document_store import InMemoryDocumentStore


def _make_corpus_dir(root: Path, corpus: str, n_files: int) -> None:
    corpus_dir = root / corpus
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        (corpus_dir / f"doc-{i}.md").write_text(f"# {corpus} doc {i}\ncontent {i}\n")


class IngestCorporaTests(unittest.TestCase):
    @patch("scripts.ingest_corpora.get_embedding_client")
    def test_ingest_tags_rows_with_corpus_name(self, mock_get_embedding_client):
        mock_client = MagicMock()
        mock_client.embed_documents.side_effect = lambda docs: [[0.1, 0.2] for _ in docs]
        mock_get_embedding_client.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_corpus_dir(root, "runbooks", 3)
            store = InMemoryDocumentStore()

            n_processed = ingest_corpus("runbooks", store, root=root)

            self.assertEqual(n_processed, 3)
            self.assertEqual(store.count("runbooks"), 3)
            for row in store.rows_for_corpus("runbooks"):
                self.assertEqual(row.corpus, "runbooks")
                self.assertIsNotNone(row.embedding)

    @patch("scripts.ingest_corpora.get_embedding_client")
    def test_ingest_is_idempotent_on_rerun(self, mock_get_embedding_client):
        mock_client = MagicMock()
        mock_client.embed_documents.side_effect = lambda docs: [[0.1] for _ in docs]
        mock_get_embedding_client.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_corpus_dir(root, "runbooks", 3)
            store = InMemoryDocumentStore()

            ingest_corpus("runbooks", store, root=root)
            first_count = store.count("runbooks")
            ingest_corpus("runbooks", store, root=root)
            second_count = store.count("runbooks")

            self.assertEqual(first_count, 3)
            self.assertEqual(first_count, second_count)

    @patch("scripts.ingest_corpora.get_embedding_client")
    def test_ingest_all_processes_each_corpus_independently(self, mock_get_embedding_client):
        mock_client = MagicMock()
        mock_client.embed_documents.side_effect = lambda docs: [[0.1] for _ in docs]
        mock_get_embedding_client.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_corpus_dir(root, "runbooks", 2)
            _make_corpus_dir(root, "postmortems", 1)
            store = InMemoryDocumentStore()

            counts = ingest_all(store, root=root)

            self.assertEqual(counts["runbooks"], 2)
            self.assertEqual(counts["postmortems"], 1)
            self.assertEqual(counts["infra_code_docs"], 0)

    @patch("scripts.ingest_corpora.get_embedding_client")
    def test_ingest_uses_client_factory(self, mock_get_embedding_client):
        mock_client = MagicMock()
        mock_client.embed_documents.side_effect = lambda docs: [[0.1] for _ in docs]
        mock_get_embedding_client.return_value = mock_client

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_corpus_dir(root, "runbooks", 1)
            store = InMemoryDocumentStore()

            ingest_corpus("runbooks", store, root=root)

            mock_get_embedding_client.assert_called_once_with(model="sentinel-embedding")


if __name__ == "__main__":
    unittest.main()
