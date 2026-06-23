"""Deterministic Tier — the cross-encoder shim itself (ADR-021 addendum,
Feature 05). Pins only that `.predict()` raises a clear NotImplementedError
(mirroring client_factory's stub clients) until Open Question #15's
real-package swap; never asserts real bge-reranker-base scores."""

import unittest

from src.reranking.cross_encoder import get_reranker_model


class CrossEncoderShimTests(unittest.TestCase):
    def test_get_reranker_model_uses_default_model_name(self):
        model = get_reranker_model()

        self.assertEqual(model.model_name, "BAAI/bge-reranker-base")

    def test_predict_raises_not_implemented(self):
        model = get_reranker_model()

        with self.assertRaises(NotImplementedError):
            model.predict([("query", "doc")])


if __name__ == "__main__":
    unittest.main()
