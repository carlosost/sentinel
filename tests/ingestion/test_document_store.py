"""Deterministic Tier — the document store shim itself (ADR-021 addendum,
Feature 04) is real project code with a real failure mode to pin: idempotent
upsert keyed on content hash, not real pgvector behavior."""

import unittest

from src.ingestion.document_store import InMemoryDocumentStore, content_hash


class DocumentStoreTests(unittest.TestCase):
    def test_upsert_tags_row_with_corpus(self):
        store = InMemoryDocumentStore()
        store.upsert(corpus="runbooks", content="abc", embedding=[0.1, 0.2])

        rows = store.rows_for_corpus("runbooks")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].corpus, "runbooks")
        self.assertEqual(rows[0].embedding, [0.1, 0.2])

    def test_upsert_is_idempotent_for_unchanged_content(self):
        store = InMemoryDocumentStore()
        store.upsert(corpus="runbooks", content="abc", embedding=[0.1])
        store.upsert(corpus="runbooks", content="abc", embedding=[0.1])

        self.assertEqual(store.count("runbooks"), 1)

    def test_different_content_creates_different_rows(self):
        store = InMemoryDocumentStore()
        store.upsert(corpus="runbooks", content="abc", embedding=[0.1])
        store.upsert(corpus="runbooks", content="xyz", embedding=[0.2])

        self.assertEqual(store.count("runbooks"), 2)

    def test_count_without_corpus_counts_all_rows(self):
        store = InMemoryDocumentStore()
        store.upsert(corpus="runbooks", content="abc", embedding=[0.1])
        store.upsert(corpus="postmortems", content="xyz", embedding=[0.2])

        self.assertEqual(store.count(), 2)
        self.assertEqual(store.count("runbooks"), 1)

    def test_content_hash_is_deterministic_and_distinguishing(self):
        self.assertEqual(content_hash("abc"), content_hash("abc"))
        self.assertNotEqual(content_hash("abc"), content_hash("xyz"))


if __name__ == "__main__":
    unittest.main()
