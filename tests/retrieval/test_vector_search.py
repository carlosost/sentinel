"""Deterministic Tier — the vector-search shim itself (ADR-021 addendum,
Feature 05) is real project code with real failure modes to pin: corpus
filtering, top-k cap, descending-score ordering, and the zero-vector edge
case. Never asserts real pgvector numerical parity."""

import math
import unittest

from src.ingestion.document_store import InMemoryDocumentStore
from src.retrieval.vector_search import (
    EmbeddingDimensionMismatchError,
    cosine_similarity,
    search,
)


class CosineSimilarityTests(unittest.TestCase):
    def test_identical_vectors_score_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)

    def test_orthogonal_vectors_score_zero(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_opposite_vectors_score_negative_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0)

    def test_zero_vector_does_not_raise_and_scores_zero(self):
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 1.0]), 0.0)

    def test_mismatched_length_raises(self):
        with self.assertRaises(ValueError):
            cosine_similarity([1.0], [1.0, 2.0])

    def test_mismatched_length_raises_named_dimension_error(self):
        """Open Question #16 (ADR-023, Feature 15) resolution: a dimension
        mismatch — e.g. the embedding fallback (bge-m3, 1024-dim) answering a
        query against a corpus ingested at 1536-dim — must raise a specific,
        named error, not an indistinguishable generic ValueError, so this
        failure mode is identifiable in logs/traces without guessing."""
        with self.assertRaises(EmbeddingDimensionMismatchError):
            cosine_similarity([1.0] * 1536, [1.0] * 1024)

    def test_known_value(self):
        score = cosine_similarity([1.0, 1.0], [1.0, 0.0])
        self.assertAlmostEqual(score, 1.0 / math.sqrt(2))


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryDocumentStore()
        self.store.upsert(corpus="runbooks", content="close", embedding=[1.0, 0.0])
        self.store.upsert(corpus="runbooks", content="far", embedding=[0.0, 1.0])
        self.store.upsert(corpus="postmortems", content="other corpus", embedding=[1.0, 0.0])

    def test_search_filters_by_corpus(self):
        results = search(self.store, "runbooks", [1.0, 0.0], k=20)

        self.assertEqual(len(results), 2)
        self.assertTrue(all(row.corpus == "runbooks" for row, _ in results))

    def test_search_orders_by_descending_score(self):
        results = search(self.store, "runbooks", [1.0, 0.0], k=20)

        scores = [score for _, score in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(results[0][0].content, "close")

    def test_search_caps_at_k(self):
        results = search(self.store, "runbooks", [1.0, 0.0], k=1)

        self.assertEqual(len(results), 1)

    def test_search_returns_fewer_than_k_without_error_if_corpus_is_smaller(self):
        results = search(self.store, "postmortems", [1.0, 0.0], k=20)

        self.assertEqual(len(results), 1)

    def test_search_raises_dimension_mismatch_instead_of_degrading_silently(self):
        """Open Question #16 (ADR-023, Feature 15): a query embedding whose
        dimension doesn't match the corpus's rows (e.g. the embedding
        fallback firing) must surface as a hard failure through `search`,
        not a silently truncated/padded comparison."""
        with self.assertRaises(EmbeddingDimensionMismatchError):
            search(self.store, "runbooks", [1.0, 0.0, 0.0], k=20)


if __name__ == "__main__":
    unittest.main()
