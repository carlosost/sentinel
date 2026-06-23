"""Deterministic Tier — grading/retry routing mechanics only (ADR-012); never
asserts whether a grade or a reformulated query is *good* — that's
Probabilistic Tier per §8.2."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.grade_documents import (
    GradeDocumentsError,
    grade_documents,
    grade_documents_route,
)


def _state(retry_count=0, current_query=None, docs=None):
    return {
        "raw_alert": "disk usage at 95% on db-primary",
        "current_query": current_query,
        "reranked_docs": docs if docs is not None else [{"content": "doc 1"}],
        "retry_count": retry_count,
    }


class GradeDocumentsNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.grade_documents.get_chat_client")
    def test_high_relevance_routes_to_diagnose(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"relevance_grade": 0.85})
        mock_get_chat_client.return_value = mock_client

        update = grade_documents(_state())
        merged = {**_state(), **update}

        self.assertEqual(update["relevance_grade"], 0.85)
        self.assertEqual(grade_documents_route(merged), "diagnose")

    @patch("src.graph.nodes.grade_documents.get_chat_client")
    def test_low_relevance_with_retries_remaining_loops_to_router(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"relevance_grade": 0.3, "reformulated_query": "alternate phrasing of the alert"}
        )
        mock_get_chat_client.return_value = mock_client

        update = grade_documents(_state(retry_count=0))
        merged = {**_state(retry_count=0), **update}

        self.assertEqual(update["retry_count"], 1)
        self.assertEqual(update["current_query"], "alternate phrasing of the alert")
        self.assertEqual(grade_documents_route(merged), "router")

    @patch("src.graph.nodes.grade_documents.get_chat_client")
    def test_low_relevance_with_retries_exhausted_proceeds_to_diagnose(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"relevance_grade": 0.3})
        mock_get_chat_client.return_value = mock_client

        update = grade_documents(_state(retry_count=2))
        merged = {**_state(retry_count=2), **update}

        self.assertEqual(update["relevance_grade"], 0.3)
        self.assertEqual(grade_documents_route(merged), "diagnose")

    @patch("src.graph.nodes.grade_documents.get_chat_client")
    def test_low_relevance_missing_reformulated_query_raises_when_retry_due(
        self, mock_get_chat_client
    ):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"relevance_grade": 0.3})
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(GradeDocumentsError):
            grade_documents(_state(retry_count=0))

    @patch("src.graph.nodes.grade_documents.get_chat_client")
    def test_grade_documents_uses_client_factory(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"relevance_grade": 0.9})
        mock_get_chat_client.return_value = mock_client

        grade_documents(_state())

        mock_get_chat_client.assert_called_once_with(model="sentinel-grader")
        mock_client.invoke.assert_called_once()

    @patch("src.graph.nodes.grade_documents.get_chat_client")
    def test_raises_on_missing_relevance_grade(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"not_relevance": 0.9})
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(GradeDocumentsError):
            grade_documents(_state())

    @patch("src.graph.nodes.grade_documents.get_chat_client")
    def test_raises_on_non_json_response(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = "not json"
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(GradeDocumentsError):
            grade_documents(_state())

    @patch("src.graph.nodes.grade_documents.get_chat_client")
    def test_third_consecutive_low_grading_gives_up_even_with_reformulated_query(
        self, mock_get_chat_client
    ):
        """retry_count=2 already means 2 retries were taken; a 3rd low grading
        must give up (route diagnose) regardless of whether a reformulated_query
        is supplied — proves the route decision is retry-budget-based, not just
        'was a reformulated_query provided.'"""
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"relevance_grade": 0.2, "reformulated_query": "yet another phrasing"}
        )
        mock_get_chat_client.return_value = mock_client

        update = grade_documents(_state(retry_count=2))
        merged = {**_state(retry_count=2), **update}

        self.assertEqual(grade_documents_route(merged), "diagnose")


if __name__ == "__main__":
    unittest.main()
