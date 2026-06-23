"""Deterministic Tier (ADR-017) — `write_postmortem`'s structural contract:
all four section headings present, the confidence-aware Notes append, the
client_factory call site, and the unconditional route to guardrail_output.
Postmortem narrative *quality* is judged elsewhere (`sentinel_remediation_judge`,
Probabilistic Tier), not here — assertions below only check structural
section-header presence, never the prose content of any section. Test names
match the feature-11 spec's pre-drafted PyTest skeletons exactly."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.write_postmortem import (
    LOW_CONFIDENCE_NOTE,
    SECTION_ACTION_TAKEN,
    SECTION_NOTES,
    SECTION_ROOT_CAUSE,
    SECTION_SUMMARY,
    write_postmortem,
)


def _base_state(**overrides) -> dict:
    state = {
        "diagnosis": "disk filling up",
        "diagnosis_confidence": "high",
        "proposed_action": {
            "tool": "fetch_additional_logs",
            "args": {},
            "side_effecting": False,
        },
        "human_decision": None,
        "execution_result": {
            "tool": "fetch_additional_logs",
            "args": {},
            "success": True,
            "output": "fetched logs",
            "error": None,
        },
    }
    state.update(overrides)
    return state


def _draft_with_all_sections() -> str:
    return (
        f"{SECTION_SUMMARY}\nDisk filled up.\n\n"
        f"{SECTION_ROOT_CAUSE}\nLog rotation disabled.\n\n"
        f"{SECTION_ACTION_TAKEN}\nFetched additional logs; succeeded.\n\n"
        f"{SECTION_NOTES}\nNone."
    )


class WritePostmortemNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.write_postmortem.get_chat_client")
    def test_postmortem_has_all_required_sections(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"postmortem_draft": _draft_with_all_sections()}
        )
        mock_get_client.return_value = mock_client

        update = write_postmortem(_base_state())

        draft = update["postmortem_draft"]
        for section in (
            SECTION_SUMMARY,
            SECTION_ROOT_CAUSE,
            SECTION_ACTION_TAKEN,
            SECTION_NOTES,
        ):
            self.assertIn(section, draft)

    @patch("src.graph.nodes.write_postmortem.get_chat_client")
    def test_low_confidence_diagnosis_is_flagged_in_notes(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"postmortem_draft": _draft_with_all_sections()}
        )
        mock_get_client.return_value = mock_client

        update = write_postmortem(_base_state(diagnosis_confidence="low"))

        self.assertIn(LOW_CONFIDENCE_NOTE, update["postmortem_draft"])

    @patch("src.graph.nodes.write_postmortem.get_chat_client")
    def test_write_postmortem_uses_client_factory(self, mock_get_client):
        """Deterministic Tier. Confirms the one LLM call goes through
        `client_factory.get_chat_client`, not a direct provider SDK call —
        same gateway-mediation contract every other LLM-calling node follows."""
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"postmortem_draft": _draft_with_all_sections()}
        )
        mock_get_client.return_value = mock_client

        write_postmortem(_base_state())

        mock_get_client.assert_called_once()
        mock_client.invoke.assert_called_once()

    @patch("src.graph.nodes.write_postmortem.get_chat_client")
    def test_write_postmortem_routes_to_guardrail_output(self, mock_get_client):
        """`write_postmortem` has no conditional routing function of its own —
        the graph wires a single static edge `write_postmortem ->
        guardrail_output` (ADR-014/ADR-017), so this test only confirms the
        node's update shape is the one `guardrail_output` expects, not a
        separate `write_postmortem_route` (none exists)."""
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps(
            {"postmortem_draft": _draft_with_all_sections()}
        )
        mock_get_client.return_value = mock_client

        update = write_postmortem(_base_state())

        self.assertIn("postmortem_draft", update)
        self.assertIsInstance(update["postmortem_draft"], str)
        self.assertTrue(len(update["postmortem_draft"]) > 0)


if __name__ == "__main__":
    unittest.main()
