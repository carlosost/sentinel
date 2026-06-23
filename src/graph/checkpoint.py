"""
Stdlib stand-in for `langgraph.checkpoint.postgres.PostgresSaver` (ADR-002,
ADR-015 — Feature 09).

SANDBOX NOTE (ADR-021 addendum, Feature 09): this dev sandbox has neither
`psycopg2`/`langgraph-checkpoint-postgres` (no PyPI egress) nor a live Postgres
instance to connect to, so the real checkpointer cannot be exercised here.
`InMemoryCheckpointSaver` below is a plain-dict stand-in that preserves the one
property this feature's Gherkin scenarios and the §1 success criterion
("survives a process restart") actually need to exercise: a checkpoint saved
by one graph object must be loadable by a *different* graph object, as long as
both share the same checkpointer instance — modeling "two processes, one
Postgres" as "two `_CompiledGraph` objects, one `InMemoryCheckpointSaver`
object" (see `tests/graph/test_hitl_checkpoint_restart.py`'s "destroy and
reinstantiate" pattern).

This shim is intentionally narrow: it stores `(state, paused_node)` tuples
in-process, keyed by `thread_id`. It does NOT persist across actual process
boundaries or survive the test runner exiting — that's the real Postgres
durability guarantee ADR-002 calls for, and this stand-in cannot provide it.
Open Question #15 tracks swapping this whole module for a real
`PostgresSaver` once this sandbox has Postgres access.
"""

from __future__ import annotations

import copy
from typing import Dict, Tuple


class CheckpointNotFoundError(KeyError):
    """Raised when `load()` is called for a `thread_id` with no saved
    checkpoint — never silently returns a fabricated empty state, since that
    would hide a caller bug (resuming a thread that was never paused, or was
    already resumed to completion and cleared)."""


class InMemoryCheckpointSaver:
    """Sandbox stand-in for `PostgresSaver`. Not thread-safe, not durable
    across process restarts — see module docstring."""

    def __init__(self) -> None:
        self._checkpoints: Dict[str, Tuple[dict, str]] = {}

    def save(self, thread_id: str, state: dict, paused_at: str) -> None:
        """Persist `state` and the node name execution paused at, keyed by
        `thread_id`. A deep copy is stored so later in-place mutation of the
        caller's `state` dict can never silently corrupt the checkpoint —
        the same discipline as a real out-of-process store, which physically
        cannot share memory with the caller."""
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
