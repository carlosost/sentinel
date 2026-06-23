"""Deterministic Tier — retriever mechanics only (ADR-011): corpus filter,
top-k=20 cap, gateway-routed embedding call, and the hard-fail on a missing
route. Never asserts which documents are 'relevant' — that's Probabilistic
Tier per §8.2."""

import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.retriever import RetrieverError, retriever
from src.ingestion.document_store import InMemoryDocumentStore


def _state(route="runbooks", raw_alert="disk usage at 95% on db-primary"):
    return {"raw_alert": raw_alert, "route": route}


def _populated_store():
    store = InMemoryDocumentStore()
    for i in range(25):
        store.upsert(corpus="runbooks", content=f"runbook {i}", embedding=[1.0, float(i)])
    store.upsert(corpus="postmortems", content="other corpus doc", embedding=[1.0, 0.0])
    return store


class RetrieverNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.retriever.get_embedding_client")
    def test_retriever_filters_by_routed_corpus_and_caps_at_top_k(self, mock_get_embedding_client):
        mock_client = MagicMock()
        mock_client.embed_documents.return_value = [[1.0, 0.0]]
        mock_get_embedding_client.return_value = mock_client
        store = _populated_store()

        update = retriever(_state(), store=store)

        docs = update["retrieved_docs"]
        self.assertEqual(len(docs), 20)
        self.assertTrue(all(doc["corpus"] == "runbooks" for doc in docs))
        for doc in docs:
            self.assertIn("content", doc)
            self.assertIn("source", doc)
            self.assertIn("score", doc)

    @patch("src.graph.nodes.retriever.get_embedding_client")
    def test_retriever_returns_fewer_than_top_k_if_corpus_smaller(self, mock_get_embedding_client):
        mock_client = MagicMock()
        mock_client.embed_documents.return_value = [[1.0, 0.0]]
        mock_get_embedding_client.return_value = mock_client
        store = InMemoryDocumentStore()
        store.upsert(corpus="postmortems", content="solo doc", embedding=[1.0, 0.0])

        update = retriever(_state(route="postmortems"), store=store)

        self.assertEqual(len(update["retrieved_docs"]), 1)

    @patch("src.graph.nodes.retriever.get_embedding_client")
    def test_retriever_uses_client_factory_for_embedding(self, mock_get_embedding_client):
        mock_client = MagicMock()
        mock_client.embed_documents.return_value = [[1.0, 0.0]]
        mock_get_embedding_client.return_value = mock_client
        store = _populated_store()

        retriever(_state(), store=store)

        mock_get_embedding_client.assert_called_once_with(model="sentinel-embedding")
        mock_client.embed_documents.assert_called_once_with(
            ["disk usage at 95% on db-primary"]
        )

    def test_retriever_raises_when_route_is_missing(self):
        with self.assertRaises(RetrieverError):
            retriever(_state(route=None), store=InMemoryDocumentStore())


if __name__ == "__main__":
    unittest.main()
