"""Golden dataset loader (ADR-008).

Stdlib-only — no extra dependency was ever needed for this module, so it is
unaffected by ADR-021's sandbox substitutions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

REQUIRED_FIELDS = (
    "incident_id",
    "alert_text",
    "reference_root_cause",
    "reference_remediation",
    "rubric",
)


class GoldenDatasetError(ValueError):
    """Raised when evals/golden_incidents.jsonl violates the ADR-008 schema."""


def load_golden_dataset(path: Union[Path, str]) -> List[Dict[str, Any]]:
    """Parse and validate evals/golden_incidents.jsonl against the ADR-008 schema.

    Raises GoldenDatasetError on: invalid JSON, missing required fields, an
    empty rubric, or duplicate incident_id values across the file.
    """
    path = Path(path)
    records: List[Dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GoldenDatasetError(f"line {lineno}: invalid JSON ({exc})") from exc

            missing = [field for field in REQUIRED_FIELDS if field not in record]
            if missing:
                raise GoldenDatasetError(
                    f"line {lineno} ({record.get('incident_id', '?')}): missing fields {missing}"
                )
            if not record["rubric"]:
                raise GoldenDatasetError(
                    f"line {lineno} ({record['incident_id']}): rubric must be non-empty"
                )
            records.append(record)

    seen: set = set()
    duplicates: set = set()
    for record in records:
        incident_id = record["incident_id"]
        if incident_id in seen:
            duplicates.add(incident_id)
        seen.add(incident_id)
    if duplicates:
        raise GoldenDatasetError(f"duplicate incident_id values: {sorted(duplicates)}")

    return records
