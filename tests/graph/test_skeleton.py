"""Deterministic Tier — integration-style test of the real entry path
(guardrail_input -> router -> retriever -> reranker -> grade_documents <-> router
loop -> diagnose -> propose_action -> guardrail_output(placeholder) | reject),
superseding Feature 01's entry->END smoke test now that real nodes exist
(ADR-009's Blast Radius note). guardrail_check, router's classification call,
retriever's embedding call, grade_documents' grading call, diagnose's call, and
propose_action's call are all mocked; the default (empty) document store means
retriever returns zero candidates and reranker short-circuits without touching
the cross-encoder. This never asserts moderation, routing, retrieval, grading,
diagnosis, or proposal accuracy — only the graph's wiring/routing contract
(ADR-010/ADR-011/ADR-012/ADR-013's Pillar Impact notes), including that the
self-RAG cycle (Feature 06's `_compat.py` addendum) actually executes
end-to-end, not just compiles."""

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
        "current_query": None,
        "diagnosis": None,
        "diagnosis_confidence": None,
        "proposed_action": None,
        "human_decision": None,
        "execution_result": None,
        "postmortem_draft": None,
        "thread_id": "test-thread-1",
    }


class GraphSkeletonTests(unittest.TestCase):
    @patch("src.graph.nodes.propose_action.get_chat_client")
    @patch("src.graph.nodes.diagnose.get_chat_client")
    @patch("src.graph.nodes.grade_documents.get_chat_client")
    @patch("src.graph.nodes.retriever.get_embedding_client")
    @patch("src.graph.nodes.router.get_chat_client")
    @patch("src.graph.nodes.guardrail_input.guardrail_check")
    def test_graph_runs_full_safe_path_high_relevance_reaches_guardrail_output_placeholder(
        self,
        mock_check,
        mock_router_chat_client,
        mock_get_embedding_client,
        mock_grader_chat_client,
        mock_diagnose_chat_client,
        mock_propose_action_chat_client,
    ):
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        mock_router_client = MagicMock()
        mock_router_client.invoke.return_value = json.dumps({"route": "runbooks"})
        mock_router_chat_client.return_value = mock_router_client
        mock_embedding_client = MagicMock()
        mock_embedding_client.embed_documents.return_value = [[0.1, 0.2]]
        mock_get_embedding_client.return_value = mock_embedding_client
        mock_grader_client = MagicMock()
        mock_grader_client.invoke.return_value = json.dumps({"relevance_grade": 0.9})
        mock_grader_chat_client.return_value = mock_grader_client
        mock_diagnose_client = MagicMock()
        mock_diagnose_client.invoke.return_value = json.dumps({"diagnosis": "disk filling up"})
        mock_diagnose_chat_client.return_value = mock_diagnose_client
        mock_propose_action_client = MagicMock()
        mock_propose_action_client.invoke.return_value = json.dumps(
            {"tool": "fetch_additional_logs", "args": {}}
        )
        mock_propose_action_chat_client.return_value = mock_propose_action_client

        graph = build_graph()
        result = graph.invoke(_initial_state())

        self.assertEqual(result["guardrail_input_verdict"]["verdict"], "safe")
        self.assertIsNone(result["rejection_reason"])
        self.assertEqual(result["route"], "runbooks")
        self.assertEqual(result["raw_alert"], "disk usage at 95% on db-primary")
        # Default (empty) document store -> no candidates -> reranker short-circuits.
        self.assertEqual(result["retrieved_docs"], [])
        self.assertEqual(result["reranked_docs"], [])
        self.assertEqual(result["relevance_grade"], 0.9)
        # router only ran once: high relevance on the first pass, no retry loop.
        mock_router_client.invoke.assert_called_once()
        self.assertEqual(result["diagnosis"], "disk filling up")
        self.assertEqual(result["diagnosis_confidence"], "high")
        self.assertEqual(
            result["proposed_action"],
            {"tool": "fetch_additional_logs", "args": {}, "side_effecting": False},
        )

    @patch("src.graph.nodes.propose_action.get_chat_client")
    @patch("src.graph.nodes.diagnose.get_chat_client")
    @patch("src.graph.nodes.grade_documents.get_chat_client")
    @patch("src.graph.nodes.retriever.get_embedding_client")
    @patch("src.graph.nodes.router.get_chat_client")
    @patch("src.graph.nodes.guardrail_input.guardrail_check")
    def test_graph_self_rag_loop_retries_twice_then_gives_up_to_diagnose(
        self,
        mock_check,
        mock_router_chat_client,
        mock_get_embedding_client,
        mock_grader_chat_client,
        mock_diagnose_chat_client,
        mock_propose_action_chat_client,
    ):
        """Proves the cycle Feature 06 added to `_compat.py` actually executes
        end-to-end: two low-relevance gradings retry back through router, a
        third gives up (ADR-012's graceful degradation) and reaches diagnose,
        which honors the hedge requirement (ADR-013) by producing
        diagnosis_confidence='low'."""
        mock_check.return_value = {"verdict": "safe", "reason": "stub"}
        mock_router_client = MagicMock()
        mock_router_client.invoke.return_value = json.dumps({"route": "runbooks"})
        mock_router_chat_client.return_value = mock_router_client
        mock_embedding_client = MagicMock()
        mock_embedding_client.embed_documents.return_value = [[0.1, 0.2]]
        mock_get_embedding_client.return_value = mock_embedding_client
        mock_grader_client = MagicMock()
        mock_grader_client.invoke.side_effect = [
            json.dumps({"relevance_grade": 0.3, "reformulated_query": "reformulated once"}),
            json.dumps({"relevance_grade": 0.3, "reformulated_query": "reformulated twice"}),
            json.dumps({"relevance_grade": 0.3}),
        ]
        mock_grader_chat_client.return_value = mock_grader_client
        mock_diagnose_client = MagicMock()
        mock_diagnose_client.invoke.return_value = json.dumps({"diagnosis": "uncertain cause"})
        mock_diagnose_chat_client.return_value = mock_diagnose_client
        mock_propose_action_client = MagicMock()
        mock_propose_action_client.invoke.return_value = json.dumps(
            {"tool": "fetch_additional_logs", "args": {}}
        )
        mock_propose_action_chat_client.return_value = mock_propose_action_client

        graph = build_graph()
        result = graph.invoke(_initial_state())

        self.assertEqual(result["relevance_grade"], 0.3)
        self.assertEqual(result["retry_count"], 3)
        self.assertEqual(result["current_query"], "reformulated twice")
        self.assertEqual(mock_router_client.invoke.call_count, 3)
        self.assertEqual(mock_grader_client.invoke.call_count, 3)
        self.assertEqual(result["diagnosis_confidence"], "low")

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
