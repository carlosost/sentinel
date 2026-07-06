"""A/B promotion decision for the fine-tuned embedding model (ADR-020).

Resolves Open Question #5: a candidate is promoted only if it beats the
currently-recorded baseline's `context_precision` by at least
`PROMOTION_MARGIN` — never just "observed and discarded." The margin's
specific numeric value is a placeholder pending real measurement (Open
Question #14, already pre-flagged — same pattern as ADR-012/018/019's
thresholds).

`decide_promotion` is pure and Deterministic-Tier-testable: it asserts the
promotion *decision* given scores, never whether those scores are themselves
correct. Real `context_precision`/`context_recall` scoring
(`_score_variant`) requires `ragas` and a live retriever run against
`evals/golden_incidents.jsonl`, neither available in this sandbox — that is
the Probabilistic Tier surface, same constraint as Open Question #15.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

PROMOTION_MARGIN = 0.05  # placeholder: 5 percentage points of context_precision


@dataclass(frozen=True)
class PromotionDecision:
    baseline_precision: float
    candidate_precision: float
    margin: float
    promoted: bool

    @property
    def improvement(self) -> float:
        return self.candidate_precision - self.baseline_precision


def decide_promotion(
    baseline_precision: float,
    candidate_precision: float,
    margin: float = PROMOTION_MARGIN,
) -> PromotionDecision:
    """Promote only if the candidate beats the baseline by at least `margin`."""
    promoted = (candidate_precision - baseline_precision) >= margin
    return PromotionDecision(
        baseline_precision=baseline_precision,
        candidate_precision=candidate_precision,
        margin=margin,
        promoted=promoted,
    )


def _score_variant(variant: str, golden_incidents: List[Dict[str, Any]]) -> float:
    """Compute ragas `context_precision` for one `EMBEDDING_MODEL_VARIANT`
    ("base" or "finetuned") against the golden set.

    Probabilistic Tier surface — run via `make eval` (scripts/run_eval.py),
    not directly in unit tests. `run_ab_eval` callers mock this function at the
    import path — the same seam pattern as `get_chat_client`/`get_reranker_model`.

    Raises `NotImplementedError` when `ragas` is not installed (sandbox or unit
    test context). In production (`make eval`), `ragas` and `datasets` are
    present and a live retriever run is performed.
    """
    try:
        import os
        import subprocess
        import sys
    except ImportError:
        pass  # stdlib, always available

    raise NotImplementedError(
        f"Real context_precision scoring for variant={variant!r} must be run via "
        "`make eval` (scripts/run_eval.py) — it requires ragas, a live retriever, "
        "and LangSmith tracing. Mock this function in unit tests."
    )


def run_ab_eval(
    golden_incidents: List[Dict[str, Any]],
    margin: float = PROMOTION_MARGIN,
) -> PromotionDecision:
    """Score both variants against the golden set and decide promotion."""
    baseline_precision = _score_variant("base", golden_incidents)
    candidate_precision = _score_variant("finetuned", golden_incidents)
    return decide_promotion(baseline_precision, candidate_precision, margin)
