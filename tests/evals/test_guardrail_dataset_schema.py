"""Deterministic Tier — schema/shape checks on evals/guardrail_redteam.jsonl
(ADR-019). These assert the dataset's structure, never any quality judgment
about whether a given example is "really" safe or unsafe."""

import json
import tempfile
import unittest
from pathlib import Path

from src.evals.guardrail_dataset import (
    REQUIRED_FIELDS,
    GuardrailDatasetError,
    load_guardrail_dataset,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDRAIL_DATASET_PATH = REPO_ROOT / "evals" / "guardrail_redteam.jsonl"


class GuardrailDatasetSchemaTests(unittest.TestCase):
    def test_every_record_has_required_fields(self):
        records = load_guardrail_dataset(GUARDRAIL_DATASET_PATH)
        self.assertGreaterEqual(len(records), 10, "expected at least 10 red-team examples")
        for record in records:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, record)

    def test_dataset_includes_both_safe_and_unsafe_examples(self):
        records = load_guardrail_dataset(GUARDRAIL_DATASET_PATH)
        verdicts = {r["expected_verdict"] for r in records}
        self.assertEqual(verdicts, {"safe", "unsafe"})

    def test_dataset_includes_both_directions(self):
        records = load_guardrail_dataset(GUARDRAIL_DATASET_PATH)
        directions = {r["direction"] for r in records}
        self.assertEqual(directions, {"input", "output"})

    def test_no_duplicate_example_ids(self):
        records = load_guardrail_dataset(GUARDRAIL_DATASET_PATH)
        ids = [r["example_id"] for r in records]
        self.assertEqual(len(ids), len(set(ids)), "duplicate example_id values found")

    def test_rejects_a_record_missing_a_required_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "bad.jsonl"
            bad_path.write_text(json.dumps({"example_id": "GR-X", "text": "missing other fields"}) + "\n")
            with self.assertRaises(GuardrailDatasetError):
                load_guardrail_dataset(bad_path)

    def test_rejects_unsafe_with_no_category(self):
        record = {
            "example_id": "GR-BAD",
            "text": "x",
            "direction": "input",
            "expected_verdict": "unsafe",
            "expected_category": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "bad.jsonl"
            bad_path.write_text(json.dumps(record) + "\n")
            with self.assertRaises(GuardrailDatasetError):
                load_guardrail_dataset(bad_path)

    def test_rejects_duplicate_ids_in_a_synthetic_fixture(self):
        record = {
            "example_id": "GR-DUP",
            "text": "x",
            "direction": "input",
            "expected_verdict": "safe",
            "expected_category": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            dup_path = Path(tmp) / "dup.jsonl"
            dup_path.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n")
            with self.assertRaises(GuardrailDatasetError):
                load_guardrail_dataset(dup_path)


if __name__ == "__main__":
    unittest.main()
