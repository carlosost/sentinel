"""Deterministic Tier — guardrail_check is mocked; asserts trigger-routing
contract (state field populated, routing target chosen), never moderation
accuracy (ADR-009)."""

import unittest
from unittest.mock import patch

from src.graph.nodes.guardrail_input import (
    ROUTE_SAFE,
    ROUTE_UNSAFE,
    guardrail_input,
    guardrail_input_route,
)


def _minimal_state(raw_alert: str = "disk usage at 95% on db-primary") -> dict:
    return {"raw_alert": raw_alert}


class GuardrailInputNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.guardrail_input.guardrail_check")
    def test_guardrail_input_routes_to_router_on_safe_verdict(self, mock_check):
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        state = _minimal_state()

        update = guardrail_input(state)
        state.update(update)

        self.assertEqual(state["guardrail_input_verdict"]["verdict"], "safe")
        self.assertEqual(guardrail_input_route(state), ROUTE_SAFE)
        mock_check.assert_called_once_with(state["raw_alert"], direction="input")

    @patch("src.graph.nodes.guardrail_input.guardrail_check")
    def test_guardrail_input_routes_to_reject_on_unsafe_verdict(self, mock_check):
        mock_check.return_value = {"verdict": "unsafe", "reason": "jailbreak-attempt"}
        state = _minimal_state()

        update = guardrail_input(state)
        state.update(update)

        self.assertEqual(state["guardrail_input_verdict"]["verdict"], "unsafe")
        self.assertEqual(guardrail_input_route(state), ROUTE_UNSAFE)


if __name__ == "__main__":
    unittest.main()
