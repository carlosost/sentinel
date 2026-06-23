"""Deterministic Tier (ADR-016) — `execute`'s outcome/routing mechanics and
ADR-015's `modified_action` precedence, mocked `mock-staging-api` responses
throughout (via `src.tools.executors.get_staging_api_client`). Whether the
action was the "right" remediation is judged elsewhere
(`sentinel_remediation_judge`, Probabilistic Tier), not here. Test names
match the feature-10 spec's pre-drafted PyTest skeletons exactly."""

import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.execute import ROUTE_FAILURE, ROUTE_SUCCESS, execute, execute_route


def _base_state(**overrides) -> dict:
    state = {
        "proposed_action": {
            "tool": "rollback_deploy",
            "args": {"to_version": "v2.3.1"},
            "side_effecting": True,
        },
        "human_decision": {"approved": True, "modified_action": None, "note": "ok"},
    }
    state.update(overrides)
    return state


class ExecuteNodeTests(unittest.TestCase):
    @patch("src.tools.executors.get_staging_api_client")
    def test_successful_execution_routes_to_write_postmortem(self, mock_get_client):
        """Deterministic Tier. Asserts execution_result.success and routing only."""
        mock_client = MagicMock()
        mock_client.call.return_value = {"success": True, "output": "rolled back"}
        mock_get_client.return_value = mock_client

        state = _base_state()
        update = execute(state)
        state.update(update)

        self.assertTrue(state["execution_result"]["success"])
        self.assertEqual(execute_route(state), ROUTE_SUCCESS)
        mock_client.call.assert_called_once_with(
            "rollback_deploy", {"to_version": "v2.3.1"}
        )

    @patch("src.tools.executors.get_staging_api_client")
    def test_failed_execution_routes_to_diagnose(self, mock_get_client):
        """Deterministic Tier. Uses failure injection per ADR-016, not a real outage."""
        mock_client = MagicMock()
        mock_client.call.return_value = {
            "success": False,
            "output": "",
            "error": "staging API returned 503",
        }
        mock_get_client.return_value = mock_client

        state = _base_state()
        update = execute(state)
        state.update(update)

        self.assertFalse(state["execution_result"]["success"])
        self.assertTrue(state["execution_result"]["error"])
        self.assertEqual(execute_route(state), ROUTE_FAILURE)

    @patch("src.tools.executors.get_staging_api_client")
    def test_modified_action_takes_precedence_over_proposed_action(self, mock_get_client):
        """Deterministic Tier. Enforces ADR-015's precedence rule at the one
        node that actually consumes it."""
        mock_client = MagicMock()
        mock_client.call.return_value = {"success": True, "output": "rolled back"}
        mock_get_client.return_value = mock_client

        state = _base_state(
            human_decision={
                "approved": True,
                "modified_action": {
                    "tool": "rollback_deploy",
                    "args": {"to_version": "v2.2.9"},
                },
                "note": "use older version",
            }
        )

        execute(state)

        mock_client.call.assert_called_once_with(
            "rollback_deploy", {"to_version": "v2.2.9"}
        )

    @patch("src.gateway.client_factory.get_embedding_client")
    @patch("src.gateway.client_factory.get_chat_client")
    @patch("src.tools.executors.get_staging_api_client")
    def test_execute_never_calls_gateway(
        self, mock_get_staging_client, mock_get_chat_client, mock_get_embedding_client
    ):
        """Deterministic Tier. Confirms the ADR-016/ADR-011 scope boundary —
        tool execution is not a gateway-mediated call."""
        mock_client = MagicMock()
        mock_client.call.return_value = {"success": True, "output": "rolled back"}
        mock_get_staging_client.return_value = mock_client

        execute(_base_state())

        mock_get_chat_client.assert_not_called()
        mock_get_embedding_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
