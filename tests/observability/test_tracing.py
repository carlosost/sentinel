"""Deterministic Tier (ADR-018) — `src.observability.tracing`'s context-var
get/set contract in isolation: default-None outside any run, set-within/
restore-after `traced_run`, and correct behavior when runs are sequential
(not nested) within one test process."""

import unittest

from src.observability.tracing import get_current_trace_id, traced_run


class TracingTests(unittest.TestCase):
    def test_no_active_run_returns_none(self):
        self.assertIsNone(get_current_trace_id())

    def test_traced_run_sets_and_restores_trace_id(self):
        self.assertIsNone(get_current_trace_id())
        with traced_run("trace-1"):
            self.assertEqual(get_current_trace_id(), "trace-1")
        self.assertIsNone(get_current_trace_id())

    def test_sequential_runs_do_not_leak_into_each_other(self):
        with traced_run("trace-a"):
            self.assertEqual(get_current_trace_id(), "trace-a")
        with traced_run("trace-b"):
            self.assertEqual(get_current_trace_id(), "trace-b")
        self.assertIsNone(get_current_trace_id())


if __name__ == "__main__":
    unittest.main()
