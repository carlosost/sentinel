"""
Checkpointer for the LangGraph HITL pause/resume mechanism (ADR-002, ADR-015).

ADR-024 (Production Readiness): `get_checkpointer(database_url)` returns a real
`langgraph.checkpoint.postgres.PostgresSaver` when both `langgraph-checkpoint-postgres`
and `psycopg` are installed and a `database_url` is provided, falling back to
`InMemoryCheckpointSaver` (the ADR-021 stdlib shim) otherwise.

`InMemoryCheckpointSaver` is kept as the fallback so `make test-local` continues to
work without a live Postgres instance. Tests that need cross-object persistence
(see `tests/graph/test_hitl_checkpoint_restart.py`) pass their own
`InMemoryCheckpointSaver` instance explicitly and are unaffected.

To use the real checkpointer in production:

    from src.graph.checkpoint import get_checkpointer
    checkpointer = get_checkpointer(os.environ["DATABASE_URL"])
    checkpointer.setup()   # idempotent — creates tables on first run
    graph = build_graph(checkpointer=checkpointer)
"""

from __future__ import annotations

import copy
from typing import Dict, Optional, Tuple

# Real PostgresSaver — used when langgraph-checkpoint-postgres + psycopg are installed.
try:
    from langgraph.checkpoint.postgres import PostgresSaver as _PostgresSaver
    import psycopg as _psycopg
    _POSTGRES_CHECKPOINTER_AVAILABLE = True
except ImportError:
    _POSTGRES_CHECKPOINTER_AVAILABLE = False


class CheckpointNotFoundError(KeyError):
    """Raised when `load()` is called for a `thread_id` with no saved
    checkpoint — never silently returns a fabricated empty state, since that
    would hide a caller bug (resuming a thread that was never paused, or was
    already resumed to completion and cleared)."""


class InMemoryCheckpointSaver:
    """In-process fallback for `PostgresSaver` (ADR-021). Not thread-safe, not
    durable across process restarts. Used automatically when
    `langgraph-checkpoint-postgres` is not installed, and explicitly by tests
    that need cross-object persistence without a live Postgres instance."""

    def __init__(self) -> None:
        self._checkpoints: Dict[str, Tuple[dict, str]] = {}

    def save(self, thread_id: str, state: dict, paused_at: str) -> None:
        """Persist `state` and the node name execution paused at, keyed by
        `thread_id`. A deep copy is stored so later in-place mutation of the
        caller's `state` dict can never silently corrupt the checkpoint."""
        self._checkpoints[thread_id] = (copy.deepcopy(state), paused_at)

    def load(self, thread_id: str) -> Tuple[dict, str]:
        try:
            state, paused_at = self._checkpoints[thread_id]
        except KeyError as exc:
            raise CheckpointNotFoundError(
                f"no checkpoint for thread_id={thread_id!r}"
            ) from exc
        return copy.deepcopy(state), paused_at

    def exists(self, thread_id: str) -> bool:
        return thread_id in self._checkpoints

    def clear(self, thread_id: str) -> None:
        self._checkpoints.pop(thread_id, None)

    def setup(self) -> None:
        """No-op on the in-memory shim. The real PostgresSaver.setup() creates
        the checkpoint tables; calling this here allows production code to call
        checkpointer.setup() unconditionally without branching on type."""


def get_checkpointer(database_url: Optional[str] = None):
    """Return the appropriate checkpointer for the current environment.

    Returns a real `PostgresSaver` (connected to `database_url`) when
    `langgraph-checkpoint-postgres` and `psycopg` are installed and a
    `database_url` is supplied. Falls back to `InMemoryCheckpointSaver` when
    either is absent — which is always the case in the dev sandbox.

    The caller must call `.setup()` on the returned checkpointer before first
    use — it is a no-op on `InMemoryCheckpointSaver` and creates the required
    Postgres tables on `PostgresSaver`.
    """
    if _POSTGRES_CHECKPOINTER_AVAILABLE and database_url:
        conn = _psycopg.connect(database_url)
        return _PostgresSaver(conn)
    return InMemoryCheckpointSaver()
