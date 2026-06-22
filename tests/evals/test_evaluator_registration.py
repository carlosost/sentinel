"""Deterministic Tier — asserts the judge evaluator is registered under the
expected stable name (ADR-008). The "LangSmith client" here is
src/evals/langsmith_registry.py's registry — a stdlib stand-in for the real
langsmith package per ADR-021 (this sandbox has no PyPI egress to install
`langsmith`); see that module's docstring and Open Question #15."""

import unittest

import src.evals.evaluator as evaluator_module  # noqa: F401  (import triggers registration)
from src.evals.langsmith_registry import LangSmithRegistryError, registry


class EvaluatorRegistrationTests(unittest.TestCase):
    def test_sentinel_remediation_judge_registered_in_langsmith(self):
        self.assertIn("sentinel_remediation_judge", registry.list_evaluators())

    def test_registered_evaluator_is_the_run_judge_function(self):
        fn = registry.get_evaluator("sentinel_remediation_judge")
        self.assertIs(fn, evaluator_module.run_judge)

    def test_unregistered_name_raises(self):
        with self.assertRaises(LangSmithRegistryError):
            registry.get_evaluator("not_a_real_evaluator")


if __name__ == "__main__":
    unittest.main()
