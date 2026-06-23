"""Deterministic Tier — registry-lookup/trust-boundary mechanics only
(ADR-013); never asserts whether the chosen tool is the *right* remediation —
that's Probabilistic Tier per §8.2."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.propose_action import ProposeActionError, propose_action


def _state(diagnosis="disk filling up on db-primary"):
    return {"diagnosis": diagnosis}


class ProposeActionNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.propose_action.get_chat_client")
    def test_side_effecting_tool_is_flagged_true(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"tool": "rollback_deploy", "args": {"deploy_id": "abc123"}}
        )
        mock_get_chat_client.return_value = mock_client

        update = propose_action(_state())

        self.assertEqual(
            update["proposed_action"],
            {"tool": "rollback_deploy", "args": {"deploy_id": "abc123"}, "side_effecting": True},
        )

    @patch("src.graph.nodes.propose_action.get_chat_client")
    def test_read_only_tool_is_flagged_false(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"tool": "fetch_additional_logs", "args": {}}
        )
        mock_get_chat_client.return_value = mock_client

        update = propose_action(_state())

        self.assertFalse(update["proposed_action"]["side_effecting"])

    @patch("src.graph.nodes.propose_action.get_chat_client")
    def test_side_effecting_is_never_trusted_from_llm_response(self, mock_get_chat_client):
        """A forged side_effecting in the LLM's JSON must be ignored — the
        registry is the only source of truth (see module docstring)."""
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"tool": "restart_service", "args": {}, "side_effecting": False}
        )
        mock_get_chat_client.return_value = mock_client

        update = propose_action(_state())

        self.assertTrue(update["proposed_action"]["side_effecting"])

    @patch("src.graph.nodes.propose_action.get_chat_client")
    def test_unknown_tool_raises_propose_action_error(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"tool": "delete_production_database", "args": {}}
        )
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(ProposeActionError):
            propose_action(_state())

    @patch("src.graph.nodes.propose_action.get_chat_client")
    def test_propose_action_uses_client_factory(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"tool": "fetch_additional_logs", "args": {}})
        mock_get_chat_client.return_value = mock_client

        propose_action(_state())

        mock_get_chat_client.assert_called_once_with(model="sentinel-propose-action")
        mock_client.invoke.assert_called_once()

    @patch("src.graph.nodes.propose_action.get_chat_client")
    def test_raises_on_non_json_response(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = "not json"
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(ProposeActionError):
            propose_action(_state())

    @patch("src.graph.nodes.propose_action.get_chat_client")
    def test_raises_on_missing_tool(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"args": {}})
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(ProposeActionError):
            propose_action(_state())


if __name__ == "__main__":
    unittest.main()
