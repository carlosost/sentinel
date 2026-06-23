"""Deterministic Tier — confidence-hedge and gateway-usage mechanics only
(ADR-013); never asserts whether a diagnosis is *correct* — that's
Probabilistic Tier, scored by `sentinel_remediation_judge` per §8.2."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.diagnose import DiagnoseError, diagnose


def _state(relevance_grade=0.9, retry_count=0):
    return {
        "raw_alert": "disk usage at 95% on db-primary",
        "current_query": None,
        "reranked_docs": [{"content": "doc 1"}],
        "relevance_grade": relevance_grade,
        "retry_count": retry_count,
    }


class DiagnoseNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.diagnose.get_chat_client")
    def test_high_relevance_yields_high_confidence(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"diagnosis": "disk filling up"})
        mock_get_chat_client.return_value = mock_client

        update = diagnose(_state(relevance_grade=0.9))

        self.assertEqual(update["diagnosis"], "disk filling up")
        self.assertEqual(update["diagnosis_confidence"], "high")

    @patch("src.graph.nodes.diagnose.get_chat_client")
    def test_low_relevance_yields_low_confidence(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"diagnosis": "uncertain cause"})
        mock_get_chat_client.return_value = mock_client

        update = diagnose(_state(relevance_grade=0.3))

        self.assertEqual(update["diagnosis_confidence"], "low")

    @patch("src.graph.nodes.diagnose.get_chat_client")
    def test_exhausted_retries_with_low_grade_yields_low_confidence(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"diagnosis": "uncertain cause"})
        mock_get_chat_client.return_value = mock_client

        update = diagnose(_state(relevance_grade=0.3, retry_count=3))

        self.assertEqual(update["diagnosis_confidence"], "low")

    @patch("src.graph.nodes.diagnose.get_chat_client")
    def test_diagnose_uses_client_factory(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"diagnosis": "disk filling up"})
        mock_get_chat_client.return_value = mock_client

        diagnose(_state())

        mock_get_chat_client.assert_called_once_with(model="sentinel-diagnose")
        mock_client.invoke.assert_called_once()

    @patch("src.graph.nodes.diagnose.get_chat_client")
    def test_raises_on_non_json_response(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = "not json"
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(DiagnoseError):
            diagnose(_state())

    @patch("src.graph.nodes.diagnose.get_chat_client")
    def test_raises_on_missing_diagnosis(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"not_diagnosis": "x"})
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(DiagnoseError):
            diagnose(_state())


if __name__ == "__main__":
    unittest.main()
