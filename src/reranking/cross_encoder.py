"""
Reranker model factory for `sentence_transformers.CrossEncoder("BAAI/bge-reranker-base")`
(ADR-011, ADR-024).

ADR-011 decided the reranker is a local, non-gateway model — it must never call
`src.gateway.client_factory`, and this module preserves that boundary by
construction (no import of, or dependency on, the gateway module).

ADR-024 (Production Readiness): `get_reranker_model()` now returns a real
`CrossEncoder` when `sentence-transformers` is installed, falling back to the
`_CrossEncoder` shim (ADR-021) otherwise. Tests mock `get_reranker_model` (or
`.predict` on its return value) at the node's import path — unaffected by this
change, since the seam is the factory function, not the class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

# Real sentence-transformers — used when installed (ADR-024).
try:
    from sentence_transformers import CrossEncoder as _RealCrossEncoder
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    _SENTENCE_TRANSFORMERS_AVAILABLE = False


@dataclass
class _CrossEncoder:
    """Stdlib shim for `sentence_transformers.CrossEncoder` (ADR-021).
    Used automatically when sentence-transformers is not installed."""

    model_name: str

    def predict(self, pairs: Sequence[Tuple[str, str]]) -> List[float]:
        raise NotImplementedError(
            f"Real inference for '{self.model_name}' requires sentence-transformers "
            "(install it and retry, or mock this in tests)."
        )


def get_reranker_model(model_name: str = "BAAI/bge-reranker-base"):
    """Return a cross-encoder reranker for the given model name.

    Returns a real `sentence_transformers.CrossEncoder` when the package is
    installed; falls back to the `_CrossEncoder` shim otherwise. Tests patch
    this function (or `.predict` on its return value) at the node's import path.
    Deliberately outside the gateway module (ADR-011).
    """
    if _SENTENCE_TRANSFORMERS_AVAILABLE:
        return _RealCrossEncoder(model_name)  # type: ignore[return-value]
    return _CrossEncoder(model_name=model_name)
