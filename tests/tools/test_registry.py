"""Deterministic Tier — registry lookup mechanics only (ADR-013)."""

import unittest

from src.tools.registry import TOOL_REGISTRY, UnknownToolError, get_tool_spec, is_side_effecting


class ToolRegistryTests(unittest.TestCase):
    def test_side_effecting_tools_are_flagged_true(self):
        for name in ("restart_service", "rollback_deploy", "page_secondary_oncall"):
            self.assertTrue(is_side_effecting(name), name)

    def test_read_only_tool_is_flagged_false(self):
        self.assertFalse(is_side_effecting("fetch_additional_logs"))

    def test_at_least_one_read_only_tool_exists(self):
        """§5.2's guardrail_output -(read-only action)-> execute branch needs at
        least one side_effecting=False tool or it's permanently dead code."""
        self.assertTrue(any(not spec["side_effecting"] for spec in TOOL_REGISTRY.values()))

    def test_unknown_tool_raises(self):
        with self.assertRaises(UnknownToolError):
            get_tool_spec("delete_production_database")


if __name__ == "__main__":
    unittest.main()
