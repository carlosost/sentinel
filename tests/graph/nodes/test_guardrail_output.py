"""Deterministic Tier — guardrail_check is mocked; asserts trigger-routing
contract (state field populated, routing target chosen, execution_result
distinguishes call sites), never moderation accuracy (ADR-009/ADR-014)."""

import unittest
from unittest.mock import patch

from src.graph.nodes.guardrail_output import (
    ROUTE_AWAIT_APPROVAL,
    ROUTE_END,
    ROUTE_EXECUTE,
    ROUTE_REJECT,
    guardrail_output,
    guardrail_output_route,
)


def _pre_execution_state(side_effecting: bool) -> dict:
    return {
        "raw_alert": "disk usage at 95% on db-primary",
        "diagnosis": "disk filling up",
        "proposed_action": {"tool": "x", "args": {}, "side_effecting": side_effecting},
        "execution_result": None,
        "postmortem_draft": None,
    }


def _post_execution_state() -> dict:
    return {
        "raw_alert": "disk usage at 95% on db-primary",
        "diagnosis": "disk filling up",
        "proposed_action": {"tool": "x", "args": {}, "side_effecting": True},
        "execution_result": {"status": "success"},
        "postmortem_draft": "## Summary\n...",
    }


class GuardrailOutputNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.guardrail_output.guardrail_check")
    def test_unsafe_pre_execution_routes_to_reject(self, mock_check):
        mock_check.return_value = {"verdict": "unsafe", "reason": "unsafe-remediation"}
        state = _pre_execution_state(side_effecting=True)

        update = guardrail_output(state)
        state.update(update)

        self.assertEqual(guardrail_output_route(state), ROUTE_REJECT)
        mock_check.assert_called_once()
        self.assertEqual(mock_check.call_args.kwargs.get("direction"), "output")

    @patch("src.graph.nodes.guardrail_output.guardrail_check")
    def test_safe_side_effecting_routes_to_await_human_approval(self, mock_check):
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        state = _pre_execution_state(side_effecting=True)

        update = guardrail_output(state)
        state.update(update)

        self.assertEqual(guardrail_output_route(state), ROUTE_AWAIT_APPROVAL)

    @patch("src.graph.nodes.guardrail_output.guardrail_check")
    def test_safe_read_only_routes_to_execute(self, mock_check):
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        state = _pre_execution_state(side_effecting=False)

        update = guardrail_output(state)
        state.update(update)

        self.assertEqual(guardrail_output_route(state), ROUTE_EXECUTE)

    @patch("src.graph.nodes.guardrail_output.guardrail_check")
    def test_unsafe_post_execution_routes_to_reject_preserves_execution_result(self, mock_check):
        mock_check.return_value = {"verdict": "unsafe", "reason": "unsafe-postmortem"}
        state = _post_execution_state()

        update = guardrail_output(state)
        state.update(update)

        self.assertEqual(guardrail_output_route(state), ROUTE_REJECT)
        self.assertEqual(state["execution_result"], {"status": "success"})

    @patch("src.graph.nodes.guardrail_output.guardrail_check")
    def test_safe_post_execution_routes_to_end(self, mock_check):
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        state = _post_execution_state()

        update = guardrail_output(state)
        state.update(update)

        self.assertEqual(guardrail_output_route(state), ROUTE_END)
        self.assertEqual(state["execution_result"], {"status": "success"})

    @patch("src.graph.nodes.guardrail_output.guardrail_check")
    def test_pre_execution_moderates_diagnosis_rendering_not_postmortem(self, mock_check):
        """postmortem_draft is unset pre-execution, so the rendered text must
        come from diagnosis/proposed_action, not silently be empty."""
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        state = _pre_execution_state(side_effecting=False)

        guardrail_output(state)

        moderated_text = mock_check.call_args.args[0]
        self.assertIn("disk filling up", moderated_text)

    @patch("src.graph.nodes.guardrail_output.guardrail_check")
    def test_post_execution_moderates_postmortem_draft(self, mock_check):
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        state = _post_execution_state()

        guardrail_output(state)

        moderated_text = mock_check.call_args.args[0]
        self.assertEqual(moderated_text, "## Summary\n...")


if __name__ == "__main__":
    unittest.main()
