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


# Module-level model cache — loaded once at first call, reused on every
# subsequent request. Loading bge-reranker-base takes ~2-4s and allocates
# ~500 MB; per-request construction would be unacceptably slow in production.
_MODEL_CACHE: dict = {}


def get_reranker_model(model_name: str = "BAAI/bge-reranker-base"):
    """Return a cross-encoder reranker for the given model name.

    **Architectural pattern — Factory + Strategy + Singleton:** this function
    is a factory that selects between two strategies (`_RealCrossEncoder` when
    `sentence-transformers` is installed, `_CrossEncoder` shim otherwise) and
    caches the result in `_MODEL_CACHE` — so the first call pays the ~2-4 s
    model-load cost, and every subsequent call is a dict lookup.  The
    Singleton aspect is intentional and scoped to the model name key: two
    different model names produce two separate cached instances.  Tests patch
    the *factory function* at the node's import path (`src.graph.nodes.reranker.
    get_reranker_model`), which means they're completely decoupled from whether
    the real or shim implementation is active — the same seam pattern used by
    `get_chat_client`, `get_checkpointer`, and `get_document_store`.

    Returns a real `sentence_transformers.CrossEncoder` when the package is
    installed; falls back to the `_CrossEncoder` shim otherwise. The model is
    loaded once on first call and cached at module level — subsequent calls for
    the same `model_name` return the cached instance with no I/O. Tests patch
    this function (or `.predict` on its return value) at the node's import path.
    Deliberately outside the gateway module (ADR-011).
    """
    if model_name not in _MODEL_CACHE:
        if _SENTENCE_TRANSFORMERS_AVAILABLE:
            _MODEL_CACHE[model_name] = _RealCrossEncoder(model_name)  # type: ignore[assignment]
        else:
            _MODEL_CACHE[model_name] = _CrossEncoder(model_name=model_name)
    return _MODEL_CACHE[model_name]
