#!/usr/bin/env python3
"""Fine-tune `BAAI/bge-small-en-v1.5` on `evals/finetune_pairs.jsonl` via a
`sentence-transformers` contrastive loss (`MultipleNegativesRankingLoss`),
writing a versioned artifact to `models/finetuned-embeddings/v{N}/` (ADR-020).

SANDBOX NOTE: `sentence-transformers` is not installable in this sandbox (no
PyPI egress — Open Question #15), so this script can only validate that the
exported pairs file is present and well-formed before a real training run; it
cannot run the fine-tune itself here. See
`tests/finetuning/test_export_finetune_pairs.py` for `build_finetune_pairs`'s
own Deterministic Tier coverage.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PAIRS_PATH = REPO_ROOT / "evals" / "finetune_pairs.jsonl"
BASE_MODEL = "BAAI/bge-small-en-v1.5"
MODEL_OUTPUT_DIR = REPO_ROOT / "models" / "finetuned-embeddings" / "v1"


def run_finetune(pairs_path: Path = PAIRS_PATH) -> int:
    """Real contrastive fine-tuning requires `sentence-transformers`, not
    available in this sandbox (Open Question #15)."""
    raise NotImplementedError(
        f"Real fine-tuning of {BASE_MODEL!r} on {pairs_path} requires "
        "sentence-transformers, not installable in this sandbox (Open Question #15)."
    )


def main() -> int:
    if not PAIRS_PATH.exists():
        print(
            f"FAIL: {PAIRS_PATH.relative_to(REPO_ROOT)} does not exist — run "
            "scripts/export_finetune_pairs.py first."
        )
        return 1

    with PAIRS_PATH.open("r", encoding="utf-8") as f:
        pairs = [json.loads(line) for line in f if line.strip()]
    print(f"  found {len(pairs)} contrastive pairs in {PAIRS_PATH.relative_to(REPO_ROOT)}.")

    try:
        run_finetune(PAIRS_PATH)
    except NotImplementedError as exc:
        print(
            f"Cannot run a real fine-tune in this sandbox (Open Question #15): {exc}"
        )
        return 0

    return 0  # pragma: no cover - unreachable until sentence-transformers lands


if __name__ == "__main__":
    sys.exit(main())
