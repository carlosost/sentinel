"""Fine-tuned local embedding model factory (ADR-020, ADR-024).

ADR-020 confirms this is the third instance of the local/non-gateway model
precedent — after the reranker (ADR-011) and tool execution (ADR-016) — so
this module must never import `src.gateway.client_factory`.

ADR-024 (Production Readiness): `get_finetuned_embedding_model()` now returns a
real `SentenceTransformer` when `sentence-transformers` is installed, falling
back to the `_LocalEmbeddingModel` shim (ADR-021) otherwise. Tests mock
`get_finetuned_embedding_model` (or `.embed_documents` on its return value) at
the node's import path — unaffected by this change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

DEFAULT_MODEL_PATH = "models/finetuned-embeddings/v1"

# Real sentence-transformers — used when installed (ADR-024).
try:
    from sentence_transformers import SentenceTransformer as _RealSentenceTransformer
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    _SENTENCE_TRANSFORMERS_AVAILABLE = False


@dataclass
class _LocalEmbeddingModel:
    """Stdlib shim for a fine-tuned `SentenceTransformer` (ADR-021).
    Used automatically when sentence-transformers is not installed."""

    model_path: str

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError(
            f"Real inference for the fine-tuned model at '{self.model_path}' "
            "requires sentence-transformers (install it and retry, or mock this in tests)."
        )


class _SentenceTransformerWrapper:
    """Thin wrapper around `SentenceTransformer` exposing `embed_documents()`
    so the fine-tuned model matches the `_LocalEmbeddingModel` interface."""

    def __init__(self, model) -> None:
        self._model = model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._model.encode(texts, convert_to_numpy=True).tolist()


def get_finetuned_embedding_model(model_path: str = DEFAULT_MODEL_PATH):
    """Return the fine-tuned local embedding model.

    Returns a `_SentenceTransformerWrapper` around a real `SentenceTransformer`
    when `sentence-transformers` is installed; falls back to `_LocalEmbeddingModel`
    otherwise. Tests patch this function (or `.embed_documents`) at the node's
    import path. Deliberately outside the gateway module (ADR-020).
    """
    if _SENTENCE_TRANSFORMERS_AVAILABLE:
        return _SentenceTransformerWrapper(_RealSentenceTransformer(model_path))
    return _LocalEmbeddingModel(model_path=model_path)
