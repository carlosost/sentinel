"""Deterministic Tier — enforces ADR-003/006 on the eval harness itself: the
judge's LLM call must go through client_factory.get_chat_client, never a
direct provider SDK import. client_factory is mocked; no real call is made."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.evals.evaluator import run_judge

INCIDENT = {
    "incident_id": "INC-TEST",
    "alert_text": "synthetic alert text",
    "reference_root_cause": "synthetic root cause",
    "reference_remediation": {"tool": "restart_service", "args": {"service": "foo"}},
    "rubric": [
        {"criterion": "correct_root_cause", "description": "first question"},
        {"criterion": "safe_action", "description": "second question"},
    ],
}


class GatewayComplianceTests(unittest.TestCase):
    @patch("src.evals.evaluator.get_chat_client")
    def test_judge_evaluator_uses_client_factory(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"correct_root_cause": True, "safe_action": True}
        )
        mock_get_chat_client.return_value = mock_client

        result = run_judge(INCIDENT)

        mock_get_chat_client.assert_called_once_with(
            model="sentinel-judge", cache={"no-cache": True}
        )
        mock_client.invoke.assert_called_once()
        self.assertTrue(result["passed"])
        self.assertEqual(result["incident_id"], "INC-TEST")

    @patch("src.evals.evaluator.get_chat_client")
    def test_aggregate_pass_is_false_if_any_criterion_is_false(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"correct_root_cause": True, "safe_action": False}
        )
        mock_get_chat_client.return_value = mock_client

        result = run_judge(INCIDENT)

        self.assertFalse(result["passed"])

    @patch("src.evals.evaluator.get_chat_client")
    def test_missing_criterion_in_judge_response_raises(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"correct_root_cause": True})
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(ValueError):
            run_judge(INCIDENT)


if __name__ == "__main__":
    unittest.main()
