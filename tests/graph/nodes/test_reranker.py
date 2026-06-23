"""Deterministic Tier — reranker mechanics only (ADR-011): count, descending
order, score-field overwrite, the empty-input short circuit, and the
gateway-isolation guarantee. Never asserts ranking correctness — Probabilistic
Tier per §8.2."""

import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.reranker import reranker


def _docs(n=20):
    return [
        {"id": str(i), "corpus": "runbooks", "content": f"doc {i}", "source": "x", "score": 0.0}
        for i in range(n)
    ]


def _state(docs):
    return {"raw_alert": "disk usage at 95% on db-primary", "retrieved_docs": docs}


class RerankerNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.reranker.get_reranker_model")
    def test_reranker_returns_top_5_by_descending_score(self, mock_get_model):
        docs = _docs(20)
        mock_model = MagicMock()
        # Reverse-indexed scores so doc 19 should win, doc 0 should lose.
        mock_model.predict.return_value = [float(i) for i in range(20)]
        mock_get_model.return_value = mock_model

        update = reranker(_state(docs))

        reranked = update["reranked_docs"]
        self.assertEqual(len(reranked), 5)
        scores = [d["score"] for d in reranked]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(reranked[0]["id"], "19")

    @patch("src.graph.nodes.reranker.get_reranker_model")
    def test_reranker_overwrites_score_field_not_adds_one(self, mock_get_model):
        docs = _docs(5)
        mock_model = MagicMock()
        mock_model.predict.return_value = [9.0, 8.0, 7.0, 6.0, 5.0]
        mock_get_model.return_value = mock_model

        update = reranker(_state(docs))

        for doc in update["reranked_docs"]:
            self.assertEqual(set(doc.keys()), {"id", "corpus", "content", "source", "score"})
        self.assertEqual(update["reranked_docs"][0]["score"], 9.0)

    def test_reranker_short_circuits_on_empty_input(self):
        update = reranker(_state([]))

        self.assertEqual(update["reranked_docs"], [])

    @patch("src.graph.nodes.reranker.get_reranker_model")
    @patch("src.gateway.client_factory.get_chat_client")
    @patch("src.gateway.client_factory.get_embedding_client")
    def test_reranker_never_calls_gateway(
        self, mock_get_embedding_client, mock_get_chat_client, mock_get_model
    ):
        mock_model = MagicMock()
        mock_model.predict.return_value = [1.0] * 5
        mock_get_model.return_value = mock_model

        reranker(_state(_docs(5)))

        mock_get_chat_client.assert_not_called()
        mock_get_embedding_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
