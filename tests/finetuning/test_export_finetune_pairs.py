"""Deterministic Tier — `build_finetune_pairs`'s contract against synthetic
LangSmith retriever/reranker span fixtures (ADR-020). Never asserts anything
about a real model's embedding quality — that is the fine-tune/A-B-eval
scripts' Probabilistic Tier concern."""

import unittest

from src.finetuning.export_pairs import ExportPairsError, build_finetune_pairs


def _doc(doc_id: str, score: float) -> dict:
    return {"id": doc_id, "corpus": "runbooks", "content": f"doc {doc_id}", "score": score}


SPAN_DISK_USAGE = {
    "query": "disk usage at 95% on db-primary",
    "retrieved_docs": [_doc("d1", 0.9), _doc("d2", 0.8), _doc("d3", 0.7)],
    "reranked_docs": [_doc("d2", 0.95), _doc("d1", 0.6)],
}

SPAN_LATENCY = {
    "query": "p99 latency spike on checkout-service",
    "retrieved_docs": [_doc("l1", 0.9), _doc("l2", 0.85)],
    "reranked_docs": [_doc("l1", 0.99)],
}


class ExportFinetunePairsTests(unittest.TestCase):
    def test_pairs_exported_from_retriever_reranker_spans_not_grade_documents(self):
        """Enforces ADR-020's corrected data source: every field read comes
        from 'retrieved_docs'/'reranked_docs', never a 'relevance_grade' or
        any other grade_documents-only field."""
        pairs = build_finetune_pairs([SPAN_DISK_USAGE])

        self.assertEqual(len(pairs), 1)
        pair = pairs[0]
        self.assertEqual(set(pair.keys()), {"query", "positive", "negative"})
        self.assertEqual(pair["query"], SPAN_DISK_USAGE["query"])
        self.assertNotIn("relevance_grade", pair["positive"])
        self.assertNotIn("relevance_grade", pair["negative"])

    def test_positive_examples_are_top_k_reranked_docs(self):
        """Positive is the highest-scoring entry of reranked_docs, never a
        retrieved_docs entry that didn't survive re-ranking."""
        pairs = build_finetune_pairs([SPAN_DISK_USAGE])

        reranked_ids = {d["id"] for d in SPAN_DISK_USAGE["reranked_docs"]}
        self.assertIn(pairs[0]["positive"]["id"], reranked_ids)
        self.assertEqual(pairs[0]["positive"]["id"], "d2")  # highest reranked score

    def test_negative_examples_did_not_survive_reranking(self):
        pairs = build_finetune_pairs([SPAN_DISK_USAGE])

        reranked_ids = {d["id"] for d in SPAN_DISK_USAGE["reranked_docs"]}
        self.assertNotIn(pairs[0]["negative"]["id"], reranked_ids)

    def test_one_pair_per_span(self):
        pairs = build_finetune_pairs([SPAN_DISK_USAGE, SPAN_LATENCY])

        self.assertEqual(len(pairs), 2)
        self.assertEqual({p["query"] for p in pairs}, {SPAN_DISK_USAGE["query"], SPAN_LATENCY["query"]})

    def test_rejects_span_missing_query(self):
        bad_span = {"retrieved_docs": [_doc("a", 0.5)], "reranked_docs": [_doc("a", 0.5)]}
        with self.assertRaises(ExportPairsError):
            build_finetune_pairs([bad_span])

    def test_rejects_span_with_no_reranked_docs(self):
        bad_span = {"query": "x", "retrieved_docs": [_doc("a", 0.5)], "reranked_docs": []}
        with self.assertRaises(ExportPairsError):
            build_finetune_pairs([bad_span])

    def test_rejects_span_with_no_negative_candidate(self):
        """Every retrieved doc survived re-ranking -> no negative example exists."""
        bad_span = {
            "query": "x",
            "retrieved_docs": [_doc("a", 0.5)],
            "reranked_docs": [_doc("a", 0.5)],
        }
        with self.assertRaises(ExportPairsError):
            build_finetune_pairs([bad_span])


if __name__ == "__main__":
    unittest.main()
