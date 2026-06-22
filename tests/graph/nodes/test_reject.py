"""Deterministic Tier — pure state-transition test, no model calls involved
(ADR-009)."""

import unittest

from src.graph.nodes.reject import reject


class RejectNodeTests(unittest.TestCase):
    def test_reject_node_records_reason_from_input_verdict(self):
        state = {
            "guardrail_input_verdict": {"verdict": "unsafe", "reason": "stub-unsafe-example"},
            "guardrail_output_verdict": None,
        }
        update = reject(state)
        self.assertEqual(update["rejection_reason"], "stub-unsafe-example")

    def test_reject_node_falls_back_to_output_verdict_if_no_input_verdict(self):
        state = {
            "guardrail_input_verdict": None,
            "guardrail_output_verdict": {"verdict": "unsafe", "reason": "output-flagged"},
        }
        update = reject(state)
        self.assertEqual(update["rejection_reason"], "output-flagged")

    def test_reject_node_reports_unknown_if_neither_verdict_present(self):
        state = {"guardrail_input_verdict": None, "guardrail_output_verdict": None}
        update = reject(state)
        self.assertEqual(update["rejection_reason"], "unknown")


if __name__ == "__main__":
    unittest.main()
