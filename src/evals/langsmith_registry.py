"""LangSmith evaluator registry (ADR-008, ADR-024).

ADR-024 (Production Readiness): when `langsmith` is installed, `registry` is
backed by a real `langsmith.Client()`. The `_EvaluatorRegistry` shim (ADR-021)
is kept as fallback so `make test-local` continues to work without a LangSmith
API key.

Both implementations expose the same interface (`register_evaluator`,
`list_evaluators`, `get_evaluator`) so CI runner code and registration code
work unchanged against either backend.
"""

from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

# Real langsmith — used when installed and LANGCHAIN_API_KEY is set (ADR-024).
try:
    from langsmith import Client as _LangSmithClient
    _LANGSMITH_AVAILABLE = True
except ImportError:
    _LANGSMITH_AVAILABLE = False


class LangSmithRegistryError(Exception):
    """Raised when an evaluator is looked up under a name that was never registered."""


class _EvaluatorRegistry:
    """In-process evaluator registry (ADR-021 shim). Used when langsmith is
    not installed or LANGCHAIN_API_KEY is not set."""

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


class _LangSmithEvaluatorRegistry:
    """Real evaluator registry backed by `langsmith.Client()` (ADR-024).

    Evaluators are registered in-process (same as the shim) but the underlying
    client is available for `scripts/run_eval.py` to call `.evaluate()` directly.
    Falls back to raising `LangSmithRegistryError` for unknown names (same
    contract as the shim).
    """

    def __init__(self, client: "_LangSmithClient") -> None:
        self._client = client
        self._evaluators: Dict[str, Callable] = {}

    @property
    def client(self) -> "_LangSmithClient":
        """The underlying langsmith Client, for scripts that need it directly."""
        return self._client

    def register_evaluator(self, name: str, fn: Callable) -> None:
        self._evaluators[name] = fn

    def list_evaluators(self) -> List[str]:
        return sorted(self._evaluators.keys())

    def get_evaluator(self, name: str) -> Callable:
        try:
            return self._evaluators[name]
        except KeyError as exc:
            raise LangSmithRegistryError(f"no evaluator registered under {name!r}") from exc


def _build_registry():
    """Return the appropriate registry for the current environment."""
    if _LANGSMITH_AVAILABLE and os.environ.get("LANGCHAIN_API_KEY"):
        return _LangSmithEvaluatorRegistry(_LangSmithClient())
    return _EvaluatorRegistry()


# Process-wide singleton — mirrors how a real langsmith.Client() would be a
# single handle shared by registration code and CI runner code.
registry = _build_registry()
