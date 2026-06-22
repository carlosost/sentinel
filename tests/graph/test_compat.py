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


if __name__ == "__main__":
    unittest.main()
