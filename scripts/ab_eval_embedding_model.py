#!/usr/bin/env python3
"""A/B-evaluate the fine-tuned embedding model against the base model using
`ragas context_precision`/`context_recall` over `evals/golden_incidents.jsonl`,
then decide promotion via `src.finetuning.ab_eval.decide_promotion` (ADR-020).

SANDBOX NOTE: real `context_precision`/`context_recall` scoring requires
`ragas` and a live retriever run, neither available in this sandbox (no PyPI
egress — Open Question #15). This script validates the golden dataset and the
promotion-decision mechanics only; see
`tests/finetuning/test_ab_eval_embedding_model.py` for `decide_promotion`'s
own Deterministic Tier coverage against mocked scores.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.evals.dataset import GoldenDatasetError, load_golden_dataset  # noqa: E402
from src.finetuning.ab_eval import run_ab_eval  # noqa: E402

GOLDEN_DATASET_PATH = REPO_ROOT / "evals" / "golden_incidents.jsonl"


def main() -> int:
    try:
        incidents = load_golden_dataset(GOLDEN_DATASET_PATH)
    except GoldenDatasetError as exc:
        print(f"FAIL: golden dataset is malformed: {exc}")
        return 1
    print(f"  loaded {len(incidents)} golden incidents to A/B-evaluate against.")

    try:
        run_ab_eval(incidents)
    except NotImplementedError as exc:
        print(
            "Cannot run a real A/B eval in this sandbox: no ragas package/live "
            f"retriever (Open Question #15). {exc}"
        )
        return 0

    return 0  # pragma: no cover - unreachable until ragas lands


if __name__ == "__main__":
    sys.exit(main())
