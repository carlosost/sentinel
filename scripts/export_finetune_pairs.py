#!/usr/bin/env python3
"""Export contrastive fine-tuning pairs from real LangSmith retriever/reranker
spans (ADR-020) into `evals/finetune_pairs.jsonl`.

SANDBOX NOTE: fetching real spans requires the `langsmith` package and a
configured project with real traces, neither available in this sandbox (no
PyPI egress — Open Question #15). This script still validates the export
mechanics (`build_finetune_pairs`'s contract) but cannot produce a real
dataset here; see `tests/finetuning/test_export_finetune_pairs.py` for the
Deterministic Tier coverage of `build_finetune_pairs` against synthetic spans.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.finetuning.export_pairs import build_finetune_pairs  # noqa: E402
from src.finetuning.langsmith_spans import get_retriever_reranker_spans  # noqa: E402

OUTPUT_PATH = REPO_ROOT / "evals" / "finetune_pairs.jsonl"


def main() -> int:
    try:
        spans = get_retriever_reranker_spans()
    except NotImplementedError as exc:
        print(
            "Cannot export real contrastive pairs in this sandbox: no "
            f"langsmith package/project egress (Open Question #15). {exc}"
        )
        return 0

    pairs = build_finetune_pairs(spans)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair) + "\n")
    print(f"Wrote {len(pairs)} contrastive pairs to {OUTPUT_PATH.relative_to(REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
