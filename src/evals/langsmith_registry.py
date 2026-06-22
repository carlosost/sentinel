"""Minimal stand-in for the LangSmith Client's evaluator registry.

ADR-021 established that this sandbox has no PyPI egress, so `langgraph`,
`langchain-openai`, `pydantic`, and `pytest` were substituted with stdlib
stand-ins for Feature 01, "and, until this constraint lifts, subsequent
features." This module is that substitution for the real `langsmith` package's
evaluator-registration surface, scoped to exactly what ADR-008 needs: register
a named evaluator function and list/retrieve registered evaluators.

Swap for the real `langsmith.Client()` once real package access exists; see
Open Question #15 (PROJECT_MEMORY.md §7), which now also covers this file.
"""

from __future__ import annotations

from typing import Callable, Dict, List


class LangSmithRegistryError(Exception):
    """Raised when an evaluator is looked up under a name that was never registered."""


class _EvaluatorRegistry:
    def __init__(self) -> None:
        self._evaluators: Dict[str, Callable] = {}

    def register_evaluator(self, name: str, fn: Callable) -> None:
        self._evaluators[name] = fn

    def list_evaluators(self) -> List[str]:
        return sorted(self._evaluators.keys())

    def get_evaluator(self, name: str) -> Callable:
        try:
            return self._evaluators[name]
        except KeyError as exc:
            raise LangSmithRegistryError(f"no evaluator registered under {name!r}") from exc


# Process-wide singleton — mirrors how a real langsmith.Client() would be a
# single handle shared by registration code and CI runner code.
registry = _EvaluatorRegistry()
