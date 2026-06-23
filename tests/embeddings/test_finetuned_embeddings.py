"""Deterministic Tier — the fine-tuned local embedding model shim itself
(ADR-020/021 addendum). Pins only that `.embed_documents()` raises a clear
NotImplementedError (mirroring `cross_encoder.py`'s `_CrossEncoder` and
`client_factory`'s stub clients) until Open Question #15's real-package swap;
never asserts real embedding values."""

import unittest

from src.embeddings.finetuned_embeddings import (
    DEFAULT_MODEL_PATH,
    get_finetuned_embedding_model,
)


class FinetunedEmbeddingsShimTests(unittest.TestCase):
    def test_get_finetuned_embedding_model_uses_default_path(self):
        model = get_finetuned_embedding_model()

        self.assertEqual(model.model_path, DEFAULT_MODEL_PATH)

    def test_get_finetuned_embedding_model_accepts_custom_path(self):
        model = get_finetuned_embedding_model("models/finetuned-embeddings/v2")

        self.assertEqual(model.model_path, "models/finetuned-embeddings/v2")

    def test_embed_documents_raises_not_implemented(self):
        model = get_finetuned_embedding_model()

        with self.assertRaises(NotImplementedError):
            model.embed_documents(["some query"])


if __name__ == "__main__":
    unittest.main()
