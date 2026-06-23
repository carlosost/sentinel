"""Deterministic Tier — the LangSmith spans-fetch shim itself (ADR-020/021
addendum). Pins only that it raises a clear NotImplementedError until Open
Question #15's real-package swap; never asserts real span content."""

import unittest

from src.finetuning.langsmith_spans import get_retriever_reranker_spans


class LangSmithSpansShimTests(unittest.TestCase):
    def test_get_retriever_reranker_spans_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            get_retriever_reranker_spans()


if __name__ == "__main__":
    unittest.main()
