"""Deterministic Tier — the shim itself (ADR-021) is real project code with real
failure modes (no branching, no cycles) that later features will hit. Pin its
behavior so the shim's limitations fail loudly and specifically, not silently."""

import unittest

from src.graph._compat import END, START, GraphNotLinearError, StateGraph


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

    def test_cycle_raises(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        graph.add_node("b", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_edge("a", "b")
        graph.add_edge("b", "a")
        with self.assertRaises(GraphNotLinearError):
            graph.compile()

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

    def test_conditional_edges_with_a_cycle_raises_at_compile_time(self):
        graph = StateGraph(dict)
        graph.add_node("a", lambda s: {})
        graph.add_node("b", lambda s: {})
        graph.add_edge(START, "a")
        graph.add_conditional_edges("a", lambda s: "loop", {"loop": "b", "done": END})
        graph.add_edge("b", "a")
        with self.assertRaises(GraphNotLinearError):
            graph.compile()

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


if __name__ == "__main__":
    unittest.main()
