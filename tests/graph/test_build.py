"""Deterministic Tier — graph compiles for the current feature set.

Feature 01's `test_empty_graph_passes_through_to_end` is retired here (not
retrofitted): it validated the placeholder entry->END skeleton before any real
node existed. Now that `guardrail_input` is real (Feature 03/ADR-009), the
end-to-end behavior is covered by tests/graph/test_skeleton.py instead — see
that file's docstring and feature-03's Blast Radius note."""

import unittest

from src.graph.build import build_graph


class GraphBuildTests(unittest.TestCase):
    def test_graph_compiles(self):
        graph = build_graph()
        self.assertIsNotNone(graph)


if __name__ == "__main__":
    unittest.main()
