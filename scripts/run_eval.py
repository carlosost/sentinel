#!/usr/bin/env python3
"""`make eval` entry point (ADR-008).

CI separation: this is deliberately not run via pytest/unittest — it is the
Probabilistic Tier eval job, reported separately from the Deterministic Tier
test suite (PROJECT_MEMORY.md §8.2). Today it can only validate the harness's
own mechanics (dataset schema, prompt rendering, evaluator registration)
because no graph node produces real diagnoses/actions yet (roadmap items
4-11) — see Feature 02's "Pillar Impact" caveat in
memory/features/feature-02-eval-harness.md. Once those nodes exist, this
script is where ragas (context_precision/context_recall/faithfulness) and the
end-to-end sentinel_remediation_judge pass rate against a stored baseline
would be wired in.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.evals.dataset import GoldenDatasetError, load_golden_dataset  # noqa: E402
from src.evals.guardrail_dataset import (  # noqa: E402
    GuardrailDatasetError,
    load_guardrail_dataset,
)
from src.evals.judge_prompt import render_judge_prompt  # noqa: E402
import src.evals.evaluator as evaluator_module  # noqa: E402,F401
from src.evals.langsmith_registry import registry  # noqa: E402

GOLDEN_DATASET_PATH = REPO_ROOT / "evals" / "golden_incidents.jsonl"
GUARDRAIL_DATASET_PATH = REPO_ROOT / "evals" / "guardrail_redteam.jsonl"


def main() -> int:
    print(f"Sentinel eval harness — {GOLDEN_DATASET_PATH.relative_to(REPO_ROOT)}")

    try:
        incidents = load_golden_dataset(GOLDEN_DATASET_PATH)
    except GoldenDatasetError as exc:
        print(f"FAIL: golden dataset is malformed: {exc}")
        return 1
    print(f"  loaded {len(incidents)} golden incidents, all schema-valid, no duplicate IDs.")

    sample = incidents[0]
    prompt = render_judge_prompt(sample)
    n_questions = len(sample["rubric"])
    print(
        f"  rendered judge prompt for {sample['incident_id']} "
        f"({n_questions} rubric criteria, {len(prompt)} chars) — OK."
    )

    evaluators = registry.list_evaluators()
    print(f"  registered evaluators: {evaluators}")
    if "sentinel_remediation_judge" not in evaluators:
        print("FAIL: sentinel_remediation_judge is not registered.")
        return 1

    try:
        redteam_examples = load_guardrail_dataset(GUARDRAIL_DATASET_PATH)
    except GuardrailDatasetError as exc:
        print(f"FAIL: guardrail red-team dataset is malformed: {exc}")
        return 1
    n_safe = sum(1 for r in redteam_examples if r["expected_verdict"] == "safe")
    n_unsafe = len(redteam_examples) - n_safe
    print(
        f"  loaded {len(redteam_examples)} guardrail red-team examples "
        f"({n_safe} safe, {n_unsafe} unsafe), all schema-valid, no duplicate IDs."
    )

    print()
    print(
        "No quality baseline yet: retriever/reranker/diagnose/propose_action "
        "(roadmap items 4-7) all exist now, but this script never invokes the "
        "real graph against golden_incidents.jsonl — ragas "
        "(context_precision/context_recall/faithfulness) and the end-to-end "
        "judge pass rate still need that wiring before a first baseline can be "
        "recorded. This run only validates harness mechanics — see ADR-008 and "
        "Feature 02's Pillar Impact caveat."
    )
    print(
        "Guardrail moderation accuracy (ADR-019) likewise has no recorded "
        "baseline yet: src.evals.guardrail_eval.score_guardrail_dataset is "
        "ready, but scoring it for real requires a live sentinel-guardrail "
        "model call, which this sandbox cannot make (no LiteLLM proxy/PyPI "
        "egress — Open Question #15). This run only validates the red-team "
        "dataset's schema and the scorer's own arithmetic (see "
        "tests/evals/test_guardrail_eval_scorer.py)."
    )
    print()
    print("Eval harness mechanics: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
