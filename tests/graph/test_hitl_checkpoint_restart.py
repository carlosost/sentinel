"""Integration Tier (ADR-015/§8.5 item 3) — exercises the interrupt/checkpoint/
restart boundary itself, not routing logic (that's covered, Deterministic
Tier, in tests/graph/nodes/test_await_human_approval.py). Deterministic in
nature throughout: asserts control-flow/persistence facts, not model-output
judgment.

SANDBOX NOTE (ADR-021 addendum, Feature 09): the spec's PyTest skeletons call
for a real test-schema Postgres-backed `PostgresSaver` (per Workflow
Blueprint §8.1's worked example (c)). This sandbox has neither `psycopg2` nor
a live Postgres instance (no PyPI egress — see ADR-021), so these tests run
against `InMemoryCheckpointSaver` (src/graph/checkpoint.py) instead. The
"destroy and reinstantiate the graph object, same Postgres instance" pattern
is modeled as "build two separate `_CompiledGraph` objects sharing one
`InMemoryCheckpointSaver` instance" — the same substitution Feature 04 made
for `InMemoryDocumentStore` standing in for pgvector. Open Question #15 tracks
re-running this exact suite against a real `PostgresSaver` once this sandbox
has Postgres access."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.graph.build import build_graph
from src.graph.checkpoint import InMemoryCheckpointSaver


def _initial_state(thread_id: str = "restart-thread-1") -> dict:
    return {
        "raw_alert": "disk usage at 95% on db-primary",
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
        "thread_id": thread_id,
    }


def _mock_side_effecting_pipeline(
    mock_check, mock_router_chat_client, mock_get_embedding_client,
    mock_grader_chat_client, mock_diagnose_chat_client, mock_propose_action_chat_client,
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
        {"tool": "restart_service", "args": {}}
    )
    mock_propose_action_chat_client.return_value = mock_propose_action_client


class HitlCheckpointRestartTests(unittest.TestCase):
    @patch("src.graph.nodes.propose_action.get_chat_client")
    @patch("src.graph.nodes.diagnose.get_chat_client")
    @patch("src.graph.nodes.grade_documents.get_chat_client")
    @patch("src.graph.nodes.retriever.get_embedding_client")
    @patch("src.graph.nodes.router.get_chat_client")
    @patch("src.graph.nodes.guardrail_input.guardrail_check")
    def test_run_pauses_at_await_human_approval_and_persists_checkpoint(
        self, mock_check, *chat_mocks
    ):
        _mock_side_effecting_pipeline(mock_check, *chat_mocks)
        test_postgres_saver = InMemoryCheckpointSaver()
        graph = build_graph(checkpointer=test_postgres_saver)
        config = {"configurable": {"thread_id": "restart-thread-1"}}

        result = graph.invoke(_initial_state(), config=config)

        self.assertIn("__interrupt__", result)
        self.assertTrue(test_postgres_saver.exists("restart-thread-1"))
        persisted_state, paused_at = test_postgres_saver.load("restart-thread-1")
        self.assertEqual(paused_at, "await_human_approval")
        self.assertEqual(persisted_state["proposed_action"]["tool"], "restart_service")

    @patch("src.graph.nodes.propose_action.get_chat_client")
    @patch("src.graph.nodes.diagnose.get_chat_client")
    @patch("src.graph.nodes.grade_documents.get_chat_client")
    @patch("src.graph.nodes.retriever.get_embedding_client")
    @patch("src.graph.nodes.router.get_chat_client")
    @patch("src.graph.nodes.guardrail_input.guardrail_check")
    def test_resume_after_simulated_process_restart_continues_correctly(
        self, mock_check, *chat_mocks
    ):
        """Kills and reinstantiates the graph object against the same
        checkpointer instance, then resumes — the core HITL durability
        guarantee from §1's success criteria."""
        _mock_side_effecting_pipeline(mock_check, *chat_mocks)
        test_postgres_saver = InMemoryCheckpointSaver()
        config = {"configurable": {"thread_id": "restart-thread-1"}}

        first_process_graph = build_graph(checkpointer=test_postgres_saver)
        paused = first_process_graph.invoke(_initial_state(), config=config)
        self.assertIn("__interrupt__", paused)
        del first_process_graph  # simulate the process dying

        # New process: a brand-new graph object, same checkpointer instance
        # (modeling "same Postgres instance" — see module docstring).
        second_process_graph = build_graph(checkpointer=test_postgres_saver)
        second_process_graph.update_state(
            config,
            {"human_decision": {"approved": True, "modified_action": None, "note": "go"}},
        )
        resumed = second_process_graph.invoke(None, config=config)

        self.assertNotIn("__interrupt__", resumed)
        self.assertEqual(resumed["human_decision"]["approved"], True)
        self.assertEqual(resumed["proposed_action"]["tool"], "restart_service")
        # Run reached END -> checkpoint cleared, not left dangling.
        self.assertFalse(test_postgres_saver.exists("restart-thread-1"))


if __name__ == "__main__":
    unittest.main()
