"""Deterministic Tier — `retriever`'s `EMBEDDING_MODEL_VARIANT` config-flag
routing (ADR-020). Enforces the ADR-011/016/020 local-model gateway-scope
precedent for the third time: the finetuned path must never touch
`client_factory`. Never asserts anything about embedding quality."""

import os
import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.retriever import EMBEDDING_MODEL_VARIANT_ENV, retriever


def _state(route: str = "runbooks") -> dict:
    return {
        "raw_alert": "disk usage at 95% on db-primary",
        "current_query": None,
        "route": route,
    }


class RetrieverModelVariantTests(unittest.TestCase):
    def setUp(self):
        self._original = os.environ.pop(EMBEDDING_MODEL_VARIANT_ENV, None)

    def tearDown(self):
        if self._original is None:
            os.environ.pop(EMBEDDING_MODEL_VARIANT_ENV, None)
        else:
            os.environ[EMBEDDING_MODEL_VARIANT_ENV] = self._original

    @patch("src.graph.nodes.retriever.get_finetuned_embedding_model")
    @patch("src.graph.nodes.retriever.get_embedding_client")
    def test_finetuned_variant_skips_gateway_embedding_client(
        self, mock_get_embedding_client, mock_get_finetuned_embedding_model
    ):
        os.environ[EMBEDDING_MODEL_VARIANT_ENV] = "finetuned"
        mock_local_model = MagicMock()
        mock_local_model.embed_documents.return_value = [[0.1, 0.2]]
        mock_get_finetuned_embedding_model.return_value = mock_local_model

        result = retriever(_state())

        mock_get_embedding_client.assert_not_called()
        mock_local_model.embed_documents.assert_called_once_with(
            ["disk usage at 95% on db-primary"]
        )
        self.assertEqual(result["retrieved_docs"], [])  # empty default store, no candidates

    @patch("src.graph.nodes.retriever.get_finetuned_embedding_model")
    @patch("src.graph.nodes.retriever.get_embedding_client")
    def test_base_variant_uses_gateway_embedding_client(
        self, mock_get_embedding_client, mock_get_finetuned_embedding_model
    ):
        os.environ[EMBEDDING_MODEL_VARIANT_ENV] = "base"
        mock_client = MagicMock()
        mock_client.embed_documents.return_value = [[0.1, 0.2]]
        mock_get_embedding_client.return_value = mock_client

        retriever(_state())

        mock_get_embedding_client.assert_called_once_with(model="sentinel-embedding")
        mock_get_finetuned_embedding_model.assert_not_called()

    @patch("src.graph.nodes.retriever.get_finetuned_embedding_model")
    @patch("src.graph.nodes.retriever.get_embedding_client")
    def test_unset_variant_defaults_to_gateway_embedding_client(
        self, mock_get_embedding_client, mock_get_finetuned_embedding_model
    ):
        mock_client = MagicMock()
        mock_client.embed_documents.return_value = [[0.1, 0.2]]
        mock_get_embedding_client.return_value = mock_client

        retriever(_state())

        mock_get_embedding_client.assert_called_once_with(model="sentinel-embedding")
        mock_get_finetuned_embedding_model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
