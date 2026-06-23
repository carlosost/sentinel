"""Deterministic Tier (ADR-016) — `execute_tool`'s dispatch/normalization
mechanics only: registry validation, response shaping into `execution_result`,
and the "client exception -> normalized failure, not a crash" contract.
`tests/graph/nodes/test_execute.py` covers the node's consumption of this
module (precedence rule, routing); this file covers the module in isolation."""

import unittest
from unittest.mock import MagicMock, patch

from src.tools.executors import ExecutorError, execute_tool


class ExecuteToolTests(unittest.TestCase):
    @patch("src.tools.executors.get_staging_api_client")
    def test_successful_call_is_normalized_into_execution_result_shape(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.call.return_value = {"success": True, "output": "done"}
        mock_get_client.return_value = mock_client

        result = execute_tool("restart_service", {"service": "api"})

        self.assertEqual(
            result,
            {
                "tool": "restart_service",
                "args": {"service": "api"},
                "success": True,
                "output": "done",
                "error": None,
            },
        )

    @patch("src.tools.executors.get_staging_api_client")
    def test_error_response_is_normalized_with_error_message(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.call.return_value = {"success": False, "error": "timeout"}
        mock_get_client.return_value = mock_client

        result = execute_tool("restart_service", {})

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "timeout")

    @patch("src.tools.executors.get_staging_api_client")
    def test_client_exception_is_normalized_into_failure_not_raised(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.call.side_effect = RuntimeError("connection refused")
        mock_get_client.return_value = mock_client

        result = execute_tool("restart_service", {})

        self.assertFalse(result["success"])
        self.assertIn("connection refused", result["error"])

    def test_unknown_tool_raises_before_any_client_call(self):
        with self.assertRaises(ExecutorError):
            execute_tool("delete_production_database", {})


if __name__ == "__main__":
    unittest.main()
