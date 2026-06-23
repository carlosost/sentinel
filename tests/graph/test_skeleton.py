"""Deterministic Tier — integration-style test of the real entry path
(guardrail_input -> router -> retriever | reject), superseding Feature 01's
entry->END smoke test now that real nodes exist (ADR-009's Blast Radius note).
guardrail_check and router's classification call are both mocked; this never
asserts moderation accuracy or routing accuracy, only the graph's
wiring/routing contract (ADR-010's Pillar Impact note)."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.graph.build import build_graph


def _initial_state(raw_alert: str = "disk usage at 95% on db-primary") -> dict:
    return {
        "raw_alert": raw_alert,
        "guardrail_input_verdict": None,
        "guardrail_output_verdict": None,
        "rejection_reason": None,
        "route": None,
        "retrieved_docs": [],
        "reranked_docs": [],
        "relevance_grade": None,
        "retry_count": 0,
        "diagnosis": None,
        "proposed_action": None,
        "human_decision": None,
        "execution_result": None,
        "postmortem_draft": None,
        "thread_id": "test-thread-1",
    }


class GraphSkeletonTests(unittest.TestCase):
    @patch("src.graph.nodes.router.get_chat_client")
    @patch("src.graph.nodes.guardrail_input.guardrail_check")
    def test_graph_runs_guardrail_input_then_router_then_retriever_on_safe_verdict(
        self, mock_check, mock_get_chat_client
    ):
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"route": "runbooks"})
        mock_get_chat_client.return_value = mock_client

        graph = build_graph()
        result = graph.invoke(_initial_state())

        self.assertEqual(result["guardrail_input_verdict"]["verdict"], "safe")
        self.assertIsNone(result["rejection_reason"])
        self.assertEqual(result["route"], "runbooks")
        self.assertEqual(result["raw_alert"], "disk usage at 95% on db-primary")

    @patch("src.graph.nodes.guardrail_input.guardrail_check")
    def test_graph_runs_guardrail_input_then_reject_on_unsafe_verdict(self, mock_check):
        mock_check.return_value = {"verdict": "unsafe", "reason": "jailbreak-attempt"}
        graph = build_graph()

        result = graph.invoke(_initial_state())

        self.assertEqual(result["guardrail_input_verdict"]["verdict"], "unsafe")
        self.assertEqual(result["rejection_reason"], "jailbreak-attempt")
        self.assertIsNone(result["route"])


if __name__ == "__main__":
    unittest.main()
