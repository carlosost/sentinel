"""Guardrail red-team dataset loader (ADR-019).

A separate file from `dataset.py`/`golden_incidents.jsonl` — ADR-008's fixed
schema for that file is untouched. Stdlib-only, same as `dataset.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

REQUIRED_FIELDS = ("example_id", "text", "direction", "expected_verdict")


class GuardrailDatasetError(ValueError):
    """Raised when evals/guardrail_redteam.jsonl violates its schema."""


def load_guardrail_dataset(path: Union[Path, str]) -> List[Dict[str, Any]]:
    """Parse and validate evals/guardrail_redteam.jsonl.

    Raises GuardrailDatasetError on: invalid JSON, missing required fields,
    an invalid `direction`/`expected_verdict` value, a `expected_verdict`/
    `expected_category` mismatch (unsafe examples must carry a category;
    safe examples must not), or duplicate `example_id` values.
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
                raise GuardrailDatasetError(f"line {lineno}: invalid JSON ({exc})") from exc

            missing = [field for field in REQUIRED_FIELDS if field not in record]
            if missing:
                raise GuardrailDatasetError(
                    f"line {lineno} ({record.get('example_id', '?')}): missing fields {missing}"
                )
            if record["direction"] not in ("input", "output"):
                raise GuardrailDatasetError(
                    f"line {lineno} ({record['example_id']}): invalid direction "
                    f"{record['direction']!r}"
                )
            if record["expected_verdict"] not in ("safe", "unsafe"):
                raise GuardrailDatasetError(
                    f"line {lineno} ({record['example_id']}): invalid expected_verdict "
                    f"{record['expected_verdict']!r}"
                )
            category = record.get("expected_category")
            if record["expected_verdict"] == "safe" and category is not None:
                raise GuardrailDatasetError(
                    f"line {lineno} ({record['example_id']}): expected_verdict='safe' "
                    f"must have a null expected_category"
                )
            if record["expected_verdict"] == "unsafe" and not category:
                raise GuardrailDatasetError(
                    f"line {lineno} ({record['example_id']}): expected_verdict='unsafe' "
                    f"must have a non-empty expected_category"
                )
            records.append(record)

    seen: set = set()
    duplicates: set = set()
    for record in records:
        example_id = record["example_id"]
        if example_id in seen:
            duplicates.add(example_id)
        seen.add(example_id)
    if duplicates:
        raise GuardrailDatasetError(f"duplicate example_id values: {sorted(duplicates)}")

    return records
