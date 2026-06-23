"""
Active-LangSmith-run trace_id context (ADR-018, Feature 12).

ADR-018 requires `client_factory` to attach the active LangSmith run's
`trace_id` as `metadata={"trace_id": ...}` on every gateway request, so the
LiteLLM proxy's cost/usage logs can be joined against LangSmith traces
(Project Charter success criterion 4).

SANDBOX NOTE (ADR-021 addendum, Feature 12): the real `langsmith` SDK exposes
this via `langsmith.run_helpers.get_current_run_tree()` inside a `@traceable`
call. This sandbox's `src/evals/langsmith_registry.py` already stands in for
the SDK's evaluator-registration surface (ADR-021); this module is the
analogous stand-in for its run-context surface, scoped to exactly what
ADR-018 needs: get/set "the current trace_id" for whatever code is running.
A `contextvars.ContextVar` is used (not a plain module global) so the
behavior is correct under concurrent/nested runs, matching how the real SDK's
context-local run tree behaves. Swap for the real SDK once this sandbox has
PyPI egress — Open Question #15's scope grows to include this module.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_current_trace_id: ContextVar[Optional[str]] = ContextVar("_current_trace_id", default=None)


def get_current_trace_id() -> Optional[str]:
    """Returns the active LangSmith run's trace_id, or None outside any
    traced run (e.g. ad hoc local/dev usage) — `client_factory` must not
    treat the absence of a trace_id as an error, only as "untraced"."""
    return _current_trace_id.get()


@contextmanager
def traced_run(trace_id: str) -> Iterator[str]:
    """Marks `trace_id` as the active run for the duration of the `with`
    block — the sandbox stand-in for entering a real `@traceable` span.
    Restores the previous value on exit, so nested/sequential runs in tests
    don't leak into each other."""
    token = _current_trace_id.set(trace_id)
    try:
        yield trace_id
    finally:
        _current_trace_id.reset(token)
