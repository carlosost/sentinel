"""
Stdlib stand-in for `sentence_transformers.CrossEncoder("BAAI/bge-reranker-base")`
(ADR-011).

ADR-011 already decided the reranker is a local, non-gateway model — it must
never call `src.gateway.client_factory`, and this shim preserves that boundary
by construction (it has no import of, or dependency on, the gateway module at
all). The only thing this shim stands in for is the absence of
`sentence-transformers` itself in this sandbox (no PyPI egress — ADR-021
addendum, Feature 05), mirroring the `_ChatClient`/`_EmbeddingClient` pattern in
`client_factory.py`: a real-shaped object whose inference method raises
`NotImplementedError` until Open Question #15's real-package swap happens.
Tests mock `get_reranker_model` (or `.predict` on its return value) the same
way other tests mock `get_chat_client`/`get_embedding_client`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple


@dataclass
class _CrossEncoder:
    model_name: str

    def predict(self, pairs: Sequence[Tuple[str, str]]) -> List[float]:
        raise NotImplementedError(
            f"Real inference for '{self.model_name}' requires sentence-transformers, "
            "not installable in this sandbox (Open Question #15)."
        )


def get_reranker_model(model_name: str = "BAAI/bge-reranker-base") -> _CrossEncoder:
    """Factory mirroring `client_factory.get_chat_client`/`get_embedding_client`'s
    shape, for the same reason: one seam tests can patch, deliberately outside
    the gateway module (ADR-011)."""
    return _CrossEncoder(model_name=model_name)
