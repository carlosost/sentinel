"""Deterministic Tier — pure state-transition / routing tests (ADR-015). No
model calls, no checkpointer involved: `await_human_approval`'s own routing
logic and `resolve_action`'s precedence rule are unit-tested directly here.
The interrupt/checkpoint/restart boundary itself is exercised separately in
`tests/graph/test_hitl_checkpoint_restart.py` (Integration Tier)."""

import unittest

from src.graph._compat import GraphInterrupt
from src.graph.nodes.await_human_approval import (
    ROUTE_APPROVED,
    ROUTE_REJECTED,
    await_human_approval,
    await_human_approval_route,
    resolve_action,
)


class AwaitHumanApprovalNodeTests(unittest.TestCase):
    def test_interrupts_when_human_decision_unset(self):
        state = {"human_decision": None, "proposed_action": {"tool": "restart_service"}}
        with self.assertRaises(GraphInterrupt) as ctx:
            await_human_approval(state)
        self.assertEqual(ctx.exception.value, {"proposed_action": {"tool": "restart_service"}})

    def test_no_op_once_human_decision_set(self):
        state = {
            "human_decision": {"approved": True, "modified_action": None, "note": "go"},
            "proposed_action": {"tool": "restart_service"},
        }
        self.assertEqual(await_human_approval(state), {})


class AwaitHumanApprovalRouteTests(unittest.TestCase):
    def test_approved_with_no_modification_routes_to_execute_with_proposed_action(self):
        """Asserts routing and that execute receives proposed_action unchanged
        when modified_action is None."""
        state = {
            "human_decision": {"approved": True, "modified_action": None, "note": "looks good"},
            "proposed_action": {"tool": "restart_service", "args": {}},
        }
        self.assertEqual(await_human_approval_route(state), ROUTE_APPROVED)
        self.assertEqual(resolve_action(state), {"tool": "restart_service", "args": {}})

    def test_approved_with_modification_routes_to_execute_with_modified_action(self):
        """Asserts the ADR-015 precedence rule: modified_action wins when present."""
        state = {
            "human_decision": {
                "approved": True,
                "modified_action": {"tool": "rollback_deploy", "args": {"to_version": "v2.2.9"}},
                "note": "use the older version",
            },
            "proposed_action": {"tool": "restart_service", "args": {}},
        }
        self.assertEqual(await_human_approval_route(state), ROUTE_APPROVED)
        self.assertEqual(
            resolve_action(state),
            {"tool": "rollback_deploy", "args": {"to_version": "v2.2.9"}},
        )

    def test_rejected_routes_to_diagnose(self):
        """Asserts routing only — does not assert how diagnose uses the
        rejection note (Open Question #9 remains open)."""
        state = {
            "human_decision": {"approved": False, "modified_action": None, "note": "wrong root cause"},
            "proposed_action": {"tool": "restart_service", "args": {}},
        }
        self.assertEqual(await_human_approval_route(state), ROUTE_REJECTED)


if __name__ == "__main__":
    unittest.main()
