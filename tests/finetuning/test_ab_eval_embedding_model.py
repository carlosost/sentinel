"""Deterministic Tier — `decide_promotion`'s threshold arithmetic and
`run_ab_eval`'s wiring against a mocked `_score_variant` (ADR-020). Asserts
the promotion *decision* given scores, never whether ragas's scores
themselves are correct — that is the Probabilistic Tier's job, same pattern
as `score_guardrail_dataset`/`sentinel_remediation_judge`."""

import unittest
from unittest.mock import patch

from src.finetuning.ab_eval import PROMOTION_MARGIN, decide_promotion, run_ab_eval


class DecidePromotionTests(unittest.TestCase):
    def test_candidate_above_margin_is_promoted(self):
        decision = decide_promotion(baseline_precision=0.70, candidate_precision=0.76)

        self.assertTrue(decision.promoted)
        self.assertAlmostEqual(decision.improvement, 0.06)

    def test_candidate_below_margin_is_not_promoted(self):
        decision = decide_promotion(baseline_precision=0.70, candidate_precision=0.72)

        self.assertFalse(decision.promoted)

    def test_candidate_exactly_at_margin_is_promoted(self):
        decision = decide_promotion(baseline_precision=0.70, candidate_precision=0.75)

        self.assertTrue(decision.promoted)

    def test_candidate_worse_than_baseline_is_not_promoted(self):
        decision = decide_promotion(baseline_precision=0.70, candidate_precision=0.50)

        self.assertFalse(decision.promoted)

    def test_custom_margin_is_respected(self):
        decision = decide_promotion(
            baseline_precision=0.70, candidate_precision=0.71, margin=0.01
        )

        self.assertTrue(decision.promoted)

    def test_default_margin_matches_module_constant(self):
        decision = decide_promotion(baseline_precision=0.70, candidate_precision=0.75)

        self.assertEqual(decision.margin, PROMOTION_MARGIN)


class RunAbEvalTests(unittest.TestCase):
    @patch("src.finetuning.ab_eval._score_variant")
    def test_run_ab_eval_promotes_when_candidate_beats_margin(self, mock_score_variant):
        mock_score_variant.side_effect = lambda variant, incidents: {
            "base": 0.70,
            "finetuned": 0.80,
        }[variant]

        decision = run_ab_eval(golden_incidents=[{"incident_id": "INC-001"}])

        self.assertTrue(decision.promoted)
        mock_score_variant.assert_any_call("base", [{"incident_id": "INC-001"}])
        mock_score_variant.assert_any_call("finetuned", [{"incident_id": "INC-001"}])

    @patch("src.finetuning.ab_eval._score_variant")
    def test_run_ab_eval_does_not_promote_when_candidate_misses_margin(self, mock_score_variant):
        mock_score_variant.side_effect = lambda variant, incidents: {
            "base": 0.70,
            "finetuned": 0.71,
        }[variant]

        decision = run_ab_eval(golden_incidents=[{"incident_id": "INC-001"}])

        self.assertFalse(decision.promoted)


if __name__ == "__main__":
    unittest.main()
