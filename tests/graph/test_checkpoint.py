"""Deterministic Tier — pins `InMemoryCheckpointSaver`'s own behavior (the
sandbox stand-in for `PostgresSaver`, ADR-021 addendum/Feature 09), including
the deep-copy isolation guarantee its docstring claims."""

import unittest

from src.graph.checkpoint import CheckpointNotFoundError, InMemoryCheckpointSaver


class InMemoryCheckpointSaverTests(unittest.TestCase):
    def test_save_then_load_round_trips_state_and_paused_node(self):
        saver = InMemoryCheckpointSaver()
        saver.save("t1", {"x": 1}, "await_human_approval")
        state, paused_at = saver.load("t1")
        self.assertEqual(state, {"x": 1})
        self.assertEqual(paused_at, "await_human_approval")

    def test_load_unknown_thread_id_raises(self):
        saver = InMemoryCheckpointSaver()
        with self.assertRaises(CheckpointNotFoundError):
            saver.load("nonexistent")

    def test_exists(self):
        saver = InMemoryCheckpointSaver()
        self.assertFalse(saver.exists("t1"))
        saver.save("t1", {}, "b")
        self.assertTrue(saver.exists("t1"))

    def test_clear_removes_checkpoint(self):
        saver = InMemoryCheckpointSaver()
        saver.save("t1", {}, "b")
        saver.clear("t1")
        self.assertFalse(saver.exists("t1"))
        saver.clear("nonexistent")  # must not raise

    def test_save_deep_copies_so_later_mutation_of_caller_state_does_not_corrupt_checkpoint(self):
        saver = InMemoryCheckpointSaver()
        original = {"nested": {"count": 1}}
        saver.save("t1", original, "b")
        original["nested"]["count"] = 999

        state, _ = saver.load("t1")
        self.assertEqual(state["nested"]["count"], 1)

    def test_load_returns_a_copy_independent_of_internal_storage(self):
        saver = InMemoryCheckpointSaver()
        saver.save("t1", {"nested": {"count": 1}}, "b")
        loaded, _ = saver.load("t1")
        loaded["nested"]["count"] = 999

        state, _ = saver.load("t1")
        self.assertEqual(state["nested"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
