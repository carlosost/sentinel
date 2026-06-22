"""Deterministic Tier — schema/shape checks on evals/golden_incidents.jsonl
(ADR-008). These assert the dataset's structure, never any quality judgment
about its content."""

import json
import unittest
from pathlib import Path

from src.evals.dataset import REQUIRED_FIELDS, GoldenDatasetError, load_golden_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DATASET_PATH = REPO_ROOT / "evals" / "golden_incidents.jsonl"


class GoldenDatasetSchemaTests(unittest.TestCase):
    def test_every_record_has_required_fields(self):
        records = load_golden_dataset(GOLDEN_DATASET_PATH)
        self.assertGreaterEqual(len(records), 20, "ADR-008 calls for 20+ golden incidents")
        for record in records:
            for field in REQUIRED_FIELDS:
                self.assertIn(field, record)
            self.assertTrue(record["rubric"], f"{record['incident_id']} has an empty rubric")
            for criterion in record["rubric"]:
                self.assertIn("criterion", criterion)
                self.assertIn("description", criterion)

    def test_no_duplicate_incident_ids(self):
        records = load_golden_dataset(GOLDEN_DATASET_PATH)
        ids = [r["incident_id"] for r in records]
        self.assertEqual(len(ids), len(set(ids)), "duplicate incident_id values found")

    def test_rejects_a_record_missing_a_required_field(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "bad.jsonl"
            bad_path.write_text(
                json.dumps({"incident_id": "INC-X", "alert_text": "missing other fields"}) + "\n"
            )
            with self.assertRaises(GoldenDatasetError):
                load_golden_dataset(bad_path)

    def test_rejects_duplicate_ids_in_a_synthetic_fixture(self):
        import tempfile

        record = {
            "incident_id": "INC-DUP",
            "alert_text": "a",
            "reference_root_cause": "b",
            "reference_remediation": {"tool": "noop", "args": {}},
            "rubric": [{"criterion": "c", "description": "d"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            dup_path = Path(tmp) / "dup.jsonl"
            dup_path.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n")
            with self.assertRaises(GoldenDatasetError):
                load_golden_dataset(dup_path)


if __name__ == "__main__":
    unittest.main()
