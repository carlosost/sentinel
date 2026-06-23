"""Deterministic Tier — the shim itself (ADR-021) is real project code with real
failure modes (malformed edges, runaway loops) that later features will hit. Pin
its behavior so the shim's limitations fail loudly and specifically, not
silently. Feature 06 added cycle support (`GraphNotLinearError` no longer covers
cycles — see `GraphRecursionError`) plus a runtime step cap as a generic safety
net against an unbounded path function. Feature 09 (ADR-015) added the
`interrupt()`/checkpointer addendum — tested below against a minimal
in-test checkpointer double, independent of `src/graph/checkpoint.py`'s own
correctness (that module has its own test file)."""

import unittest

from src.graph._compat import (
    END,
    START,
    GraphInterrupt,
    GraphNotLinearError,
    GraphRecursionError,
    StateGraph,
    interrupt,
)


class _DictCheckpointer:
    """Minimal in-test stand-in so these shim-level tests don't depend on
    `src/graph/checkpoint.py`'s own correctness."""

    def __init__(self):
        self.store = {}

    def save(self, thread_id, state, paused_at):
        self.store[thread_id] = (dict(state), paused_at)

    def load(self, thread_id):
        state, paused_at = self.store[thread_id]
        return dict(state), paused_at

    def exists(self, thread_id):
        return thread_id in self.store

    def clear(self, thread_id):
        self.store.pop(thread_id, None)


class CompatShimTests(unittest.TestCase):
    def test_linear_two_node_chain(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {"a_ran": True})
        graph.add_node("b", lambda s: {"b_ran": True})
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        graph.add_edge("b", END)
        compiled = graph.compile()
        result = compiled.invoke({})
        self.assertTrue(result["a_ran"])
        self.assertTrue(result["b_ran"])

    def test_missing_entry_edge_raises(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        with self.assertRaises(GraphNotLinearError):
            graph.compile()

    def test_branching_raises(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        graph.add_node("b", lambda s: {})
        graph.add_node("c", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        with self.assertRaises(GraphNotLinearError):
            graph.add_edge("a", "c")

    def test_cycle_compiles_and_runs_until_a_path_function_breaks_it(self):
        """Feature 06: cycles are now permitted. This graph loops a->b->a until
        the path function (reading a counter the nodes increment) sends it to
        END — proving the cycle actually executes, not just compiles."""
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {"count": s.get("count", 0) + 1})
        graph.add_node("b", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_conditional_edges(
            "a", lambda s: "done" if s["count"] >= 3 else "loop", {"done": END, "loop": "b"}
        )
        graph.add_edge("b", "a")

        compiled = graph.compile()
        result = compiled.invoke({})

        self.assertEqual(result["count"], 3)

    def test_unbounded_cycle_raises_graph_recursion_error(self):
        """The runtime safety net: a path function that never reaches END must
        fail loudly within max_steps, not hang."""
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        graph.add_node("b", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_conditional_edges("a", lambda s: "loop", {"loop": "b"})
        graph.add_edge("b", "a")

        compiled = graph.compile()

        with self.assertRaises(GraphRecursionError):
            compiled.invoke({}, max_steps=10)

    def test_conditional_edges_route_to_the_correct_branch(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {"a_ran": True})
        graph.add_node("safe_branch", lambda s: {"branch": "safe"})
        graph.add_node("unsafe_branch", lambda s: {"branch": "unsafe"})
        graph.add_edge(START, "a")
        graph.add_conditional_edges(
            "a",
            lambda s: "ok" if s.get("verdict") == "safe" else "bad",
            {"ok": "safe_branch", "bad": "unsafe_branch"},
        )
        graph.add_edge("safe_branch", END)
        graph.add_edge("unsafe_branch", END)
        compiled = graph.compile()

        safe_result = compiled.invoke({"verdict": "safe"})
        self.assertEqual(safe_result["branch"], "safe")

        unsafe_result = compiled.invoke({"verdict": "unsafe"})
        self.assertEqual(unsafe_result["branch"], "unsafe")

    def test_conditional_edges_can_target_end_directly(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_conditional_edges("a", lambda s: "done", {"done": END})
        compiled = graph.compile()
        result = compiled.invoke({})
        self.assertEqual(result, {})

    def test_conditional_edges_with_a_cycle_compile_fine(self):
        """Feature 06: a conditional-edge cycle is exactly Sentinel's
        grade_documents->router shape — must compile without error."""
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        graph.add_node("b", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_conditional_edges("a", lambda s: "done", {"loop": "b", "done": END})
        graph.add_edge("b", "a")

        compiled = graph.compile()  # must not raise

        self.assertEqual(compiled.invoke({}), {})

    def test_path_function_returning_unknown_key_raises_at_runtime(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        graph.add_node("b", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_conditional_edges("a", lambda s: "not_a_real_key", {"ok": "b"})
        graph.add_edge("b", END)
        compiled = graph.compile()
        with self.assertRaises(GraphNotLinearError):
            compiled.invoke({})

    def test_node_with_both_static_and_conditional_edge_raises(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        graph.add_node("b", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        with self.assertRaises(GraphNotLinearError):
            graph.add_conditional_edges("a", lambda s: "x", {"x": "b"})


class InterruptCheckpointTests(unittest.TestCase):
    """Feature 09/ADR-015 addendum."""

    def _pausing_graph(self, checkpointer):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {"a_ran": True})

        def b(s):
            if s.get("approved") is None:
                interrupt({"reason": "needs approval"})
            return {}

        graph.add_node("b", b)
        graph.add_node("c", lambda s: {"c_ran": True})
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        graph.add_edge("b", "c")
        graph.add_edge("c", END)
        return graph.compile(checkpointer=checkpointer)

    def test_interrupt_without_checkpointer_propagates(self):
        compiled = self._pausing_graph(checkpointer=None)
        with self.assertRaises(GraphInterrupt):
            compiled.invoke({}, config={"configurable": {"thread_id": "t1"}})

    def test_interrupt_with_checkpointer_and_thread_id_pauses_and_persists(self):
        checkpointer = _DictCheckpointer()
        compiled = self._pausing_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "t1"}}

        result = compiled.invoke({}, config=config)

        self.assertTrue(result["a_ran"])
        self.assertEqual(result["__interrupt__"], {"reason": "needs approval"})
        self.assertTrue(checkpointer.exists("t1"))
        state, paused_at = checkpointer.load("t1")
        self.assertEqual(paused_at, "b")

    def test_resume_with_no_input_continues_from_paused_node(self):
        checkpointer = _DictCheckpointer()
        compiled = self._pausing_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "t1"}}

        compiled.invoke({}, config=config)
        compiled.update_state(config, {"approved": True})
        result = compiled.invoke(None, config=config)

        self.assertTrue(result["c_ran"])
        self.assertNotIn("__interrupt__", result)
        self.assertFalse(checkpointer.exists("t1"))

    def test_resume_without_checkpointer_or_thread_id_raises(self):
        compiled = self._pausing_graph(checkpointer=None)
        with self.assertRaises(ValueError):
            compiled.invoke(None, config={"configurable": {"thread_id": "t1"}})

        checkpointer = _DictCheckpointer()
        compiled_with_checkpointer = self._pausing_graph(checkpointer=checkpointer)
        with self.assertRaises(ValueError):
            compiled_with_checkpointer.invoke(None, config=None)

    def test_update_state_without_existing_checkpoint_raises(self):
        checkpointer = _DictCheckpointer()
        compiled = self._pausing_graph(checkpointer=checkpointer)
        with self.assertRaises(KeyError):
            compiled.update_state({"configurable": {"thread_id": "nonexistent"}}, {"approved": True})


if __name__ == "__main__":
    unittest.main()
