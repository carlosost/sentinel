"""Deterministic Tier — string/template rendering check on
src/evals/judge_prompt.py (ADR-008). Asserts shape of the rendered prompt, not
judge output quality."""

import unittest

from src.evals.judge_prompt import render_judge_prompt

INCIDENT = {
    "incident_id": "INC-TEST",
    "alert_text": "synthetic alert text",
    "reference_root_cause": "synthetic root cause",
    "reference_remediation": {"tool": "restart_service", "args": {"service": "foo"}},
    "rubric": [
        {"criterion": "correct_root_cause", "description": "first question"},
        {"criterion": "safe_action", "description": "second question"},
        {"criterion": "within_policy", "description": "third question"},
    ],
}


class JudgePromptRenderingTests(unittest.TestCase):
    def test_renders_one_yes_no_question_per_rubric_criterion(self):
        rendered = render_judge_prompt(INCIDENT)
        for item in INCIDENT["rubric"]:
            self.assertIn(item["description"], rendered)
            self.assertIn(f"`{item['criterion']}`", rendered)

    def test_requests_json_output_with_exactly_those_boolean_keys(self):
        rendered = render_judge_prompt(INCIDENT)
        for item in INCIDENT["rubric"]:
            self.assertIn(f'"{item["criterion"]}": true|false', rendered)
        # No leftover template tokens.
        self.assertNotIn("{{", rendered)
        self.assertNotIn("}}", rendered)

    def test_proposed_answer_defaults_when_not_supplied(self):
        rendered = render_judge_prompt(INCIDENT)
        self.assertIn("(not yet available)", rendered)

    def test_proposed_answer_is_substituted_when_supplied(self):
        rendered = render_judge_prompt(
            INCIDENT,
            {"diagnosis": "a diagnosis", "proposed_action": "an action"},
        )
        self.assertIn("a diagnosis", rendered)
        self.assertIn("an action", rendered)


if __name__ == "__main__":
    unittest.main()
