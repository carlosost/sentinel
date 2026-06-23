"""Stdlib stand-in for a locally-loaded, fine-tuned `sentence-transformers`
embedding model (ADR-020).

ADR-020 confirms this is the **third** instance of the local/non-gateway model
precedent — after the reranker (ADR-011) and tool execution (ADR-016) — so
this module must never import `src.gateway.client_factory`, and (like
`src/reranking/cross_encoder.py`) it has no dependency on the gateway module
at all, preserving that boundary by construction.

The only thing this shim stands in for is the absence of
`sentence-transformers` itself in this sandbox (no PyPI egress — ADR-021
addendum), mirroring `cross_encoder.py`'s `_CrossEncoder` pattern: a
real-shaped object whose inference method raises `NotImplementedError` until
Open Question #15's real-package swap happens. Tests mock
`get_finetuned_embedding_model` (or `.embed_documents` on its return value)
the same way other tests mock `get_chat_client`/`get_reranker_model`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

DEFAULT_MODEL_PATH = "models/finetuned-embeddings/v1"


@dataclass
class _LocalEmbeddingModel:
    model_path: str

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError(
            f"Real inference for the fine-tuned model at '{self.model_path}' "
            "requires sentence-transformers, not installable in this sandbox "
            "(Open Question #15)."
        )


def get_finetuned_embedding_model(
    model_path: str = DEFAULT_MODEL_PATH,
) -> _LocalEmbeddingModel:
    """Factory mirroring `client_factory.get_embedding_client`/
    `cross_encoder.get_reranker_model`'s shape: one seam tests can patch,
    deliberately outside the gateway module (ADR-020)."""
    return _LocalEmbeddingModel(model_path=model_path)
