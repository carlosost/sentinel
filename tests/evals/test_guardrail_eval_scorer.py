"""Deterministic Tier — `score_guardrail_dataset`'s confusion-matrix/precision/
recall arithmetic in isolation, against a fake `classify` callable. Never
asserts anything about a real model's moderation accuracy — that is the
Probabilistic Tier's job (`make eval`, scored against a stored threshold, not
`assert ==`, same pattern as ragas/sentinel_remediation_judge)."""

import unittest

from src.evals.guardrail_eval import score_guardrail_dataset

RECORDS = [
    {"text": "a", "direction": "input", "expected_verdict": "unsafe"},
    {"text": "b", "direction": "input", "expected_verdict": "unsafe"},
    {"text": "c", "direction": "input", "expected_verdict": "safe"},
    {"text": "d", "direction": "input", "expected_verdict": "safe"},
]


class GuardrailEvalScorerTests(unittest.TestCase):
    def test_perfect_classifier_scores_1_0_precision_and_recall(self):
        def classify(text, direction):
            expected = next(r["expected_verdict"] for r in RECORDS if r["text"] == text)
            return {"verdict": expected}

        result = score_guardrail_dataset(RECORDS, classify)

        self.assertEqual(result.precision, 1.0)
        self.assertEqual(result.recall, 1.0)
        self.assertEqual(result.true_positives, 2)
        self.assertEqual(result.true_negatives, 2)
        self.assertEqual(result.false_positives, 0)
        self.assertEqual(result.false_negatives, 0)

    def test_classifier_that_always_says_safe_has_zero_recall(self):
        def classify(text, direction):
            return {"verdict": "safe"}

        result = score_guardrail_dataset(RECORDS, classify)

        self.assertEqual(result.recall, 0.0)
        self.assertEqual(result.false_negatives, 2)
        self.assertEqual(result.precision, 0.0)  # no positives predicted at all -> 0.0, not divide-by-zero

    def test_classifier_that_always_says_unsafe_has_perfect_recall_low_precision(self):
        def classify(text, direction):
            return {"verdict": "unsafe"}

        result = score_guardrail_dataset(RECORDS, classify)

        self.assertEqual(result.recall, 1.0)
        self.assertEqual(result.false_positives, 2)
        self.assertEqual(result.precision, 0.5)


if __name__ == "__main__":
    unittest.main()
