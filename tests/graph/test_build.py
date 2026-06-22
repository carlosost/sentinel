"""Deterministic Tier — Feature 01's graph is just entry -> END. Asserts the graph
compiles and a run completes without error, returning the input state unchanged
(no real node logic exists yet)."""

import unittest

from src.graph.build import build_graph


class GraphBuildTests(unittest.TestCase):
    def test_graph_compiles(self):
        graph = build_graph()
        self.assertIsNotNone(graph)

    def test_empty_graph_passes_through_to_end(self):
        graph = build_graph()
        initial_state = {
            "raw_alert": "disk usage at 95% on db-primary",
            "guardrail_input_verdict": None,
            "guardrail_output_verdict": None,
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
        result = graph.invoke(initial_state)
        self.assertEqual(result["raw_alert"], "disk usage at 95% on db-primary")


if __name__ == "__main__":
    unittest.main()
