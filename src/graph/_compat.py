"""
Minimal stdlib stand-in for the slice of `langgraph.graph` Sentinel currently uses.

SANDBOX NOTE (ADR-021): this dev sandbox has no PyPI egress, so the real `langgraph`
package is not installable here. This shim implements `START`/`END` sentinels and a
`StateGraph` supporting:
  - `add_node` / `add_edge` — a strictly linear segment: each node may have at most
    one *static* outgoing edge.
  - `add_conditional_edges(source, path, path_map)` (added for Feature 03) — the
    sanctioned way to branch, mirroring real langgraph's own API (real langgraph
    also models branching this way, not via multiple `add_edge` calls from one
    node). `path` is called with the current state and must return a key present in
    `path_map`; `path_map` maps that key to a target node name (or `END`).
  - Cycles (added for Feature 06 — the self-RAG retry loop is the graph's first
    one): `compile()` no longer rejects a structural cycle; it only checks that
    every edge target is a known node (or `END`) and that an entry edge exists.
    `invoke()` enforces a `max_steps` runtime cap (default 25, matching real
    langgraph's default `recursion_limit`) and raises `GraphRecursionError` if a
    run exceeds it — a generic safety net against a runaway path function, not
    something well-formed graphs (like Sentinel's, whose loop is bounded by
    `grade_documents`' own retry cap) should ever hit.

Feature 09 (ADR-015) adds interrupt()/checkpoint support — the addendum below —
following the same pattern as Feature 06's cycle-support addendum: extend this
shim in place rather than rewrite it, and call out exactly what's added.

ADDENDUM (Feature 09 — HITL interrupt/resume):
  - `interrupt(value)`: raises `GraphInterrupt(value)`. Unlike real langgraph's
    `interrupt()` (which suspends and, on resume, *returns* a value to the
    caller via a generator-replay mechanism this stdlib shim has no way to
    faithfully reproduce), this shim's `interrupt()` always raises — it never
    returns. A node that wants different behavior on resume must check its own
    state for whatever the human/caller wrote back (e.g. `await_human_approval`
    checks `state.get("human_decision")`) rather than relying on `interrupt()`'s
    return value. This is a deliberate, documented simplification, not a bug —
    see `src/graph/nodes/await_human_approval.py`'s docstring for how the one
    node that uses this is written around the limitation.
  - `compile(checkpointer=None)`: a compiled graph may now be given a
    checkpointer (see `src/graph/checkpoint.py`'s `InMemoryCheckpointSaver`,
    the sandbox stand-in for real `langgraph.checkpoint.postgres.PostgresSaver`
    per ADR-002/015). Without one, `invoke()` behaves exactly as before
    (Features 01-08); an uncaught `GraphInterrupt` simply propagates, which is
    correct — there is nowhere to persist the pause.
  - `invoke(input_, *, config=None, max_steps=...)`: `config` may carry
    `{"configurable": {"thread_id": ...}}`, mirroring real langgraph's API
    surface. When a node raises `GraphInterrupt` during a run that has both a
    checkpointer and a `thread_id`, the run halts, the in-flight state and the
    paused node's name are persisted via the checkpointer, and `invoke()`
    returns `{**state, "__interrupt__": <value>}` instead of raising.
  - `invoke(None, config=...)`: resumes a previously-paused thread — loads the
    persisted `(state, paused_node)` from the checkpointer and continues
    execution from `paused_node` (re-running it; see the `interrupt()` note
    above for why this is safe for `await_human_approval` specifically).
  - `update_state(config, values)`: merges `values` into a paused thread's
    persisted state without resuming execution — this is how a human's
    decision is written back before the resume call, matching the
    `update_state(...)` then `invoke(None, config=...)` two-step real langgraph
    itself uses for this exact pattern (see PROJECT_MEMORY.md §3 Pillar 2).

This shim still does NOT support real `langgraph`'s generator-based `interrupt()`
return-value semantics, or genuine cross-process persistence (the checkpointer
is in-process memory, not a real Postgres connection) — Open Question #15
tracks replacing this shim (and `InMemoryCheckpointSaver`) with the real
packages, re-verifying every node wired against it, before any feature ships
its "real" implementation against actual infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

START = "__start__"
END = "__end__"

DEFAULT_MAX_STEPS = 25

NodeFn = Callable[[dict], dict]
PathFn = Callable[[dict], str]


class GraphNotLinearError(RuntimeError):
    """Raised when an edge is malformed (duplicate outgoing edge from a node,
    unknown target, missing entry edge). No longer raised for cycles — see
    `GraphRecursionError` for the runtime safety net that replaces it."""


class GraphRecursionError(RuntimeError):
    """Raised when a single `invoke()` run exceeds `max_steps` node executions —
    real langgraph's own `recursion_limit` behavior. A well-formed cyclic graph
    (one whose nodes themselves bound the loop, e.g. `grade_documents`' retry
    cap) should never hit this; it exists to fail loudly on a path function bug
    that produces an unbounded loop, rather than hanging."""


class GraphInterrupt(Exception):
    """Raised by `interrupt(value)` (Feature 09/ADR-015) to pause a run. Caught
    by `_CompiledGraph.invoke()`, which persists the pause via the configured
    checkpointer if one and a `thread_id` are available — otherwise this
    propagates uncaught, since there is nowhere to persist the pause."""

    def __init__(self, value: Any):
        super().__init__(value)
        self.value = value


def interrupt(value: Any) -> Any:
    """Pause the current node (Feature 09/ADR-015). Always raises
    `GraphInterrupt(value)` — see this module's docstring addendum for why
    this shim cannot faithfully reproduce real langgraph's "returns a value on
    resume" behavior, and how `await_human_approval` is written around that."""
    raise GraphInterrupt(value)


@dataclass(frozen=True)
class _ConditionalEdge:
    path: PathFn
    path_map: dict[str, str]


class _CompiledGraph:
    def __init__(
        self,
        entry: str,
        nodes: dict[str, NodeFn],
        static_edges: dict[str, str],
        conditional_edges: dict[str, _ConditionalEdge],
        checkpointer: Optional[Any] = None,
    ):
        self._entry = entry
        self._nodes = nodes
        self._static_edges = static_edges
        self._conditional_edges = conditional_edges
        self._checkpointer = checkpointer

    def _next(self, current: str, state: dict) -> str:
        if current in self._conditional_edges:
            edge = self._conditional_edges[current]
            key = edge.path(state)
            if key not in edge.path_map:
                raise GraphNotLinearError(
                    f"path function for '{current}' returned {key!r}, which is not "
                    f"in its path_map {sorted(edge.path_map)}"
                )
            return edge.path_map[key]
        return self._static_edges.get(current, END)

    @staticmethod
    def _thread_id(config: Optional[dict]) -> Optional[str]:
        if not config:
            return None
        return config.get("configurable", {}).get("thread_id")

    def update_state(self, config: dict, values: dict) -> None:
        """Merge `values` into a paused thread's persisted state without
        resuming execution (Feature 09/ADR-015) — the step that writes a
        human's decision back before the `invoke(None, config=...)` resume
        call. Requires a checkpointer and a thread_id with an existing
        checkpoint (i.e. a thread that is actually paused)."""
        thread_id = self._thread_id(config)
        if self._checkpointer is None or thread_id is None:
            raise ValueError("update_state requires a checkpointer and a thread_id")
        state, paused_at = self._checkpointer.load(thread_id)
        state.update(values)
        self._checkpointer.save(thread_id, state, paused_at)

    def invoke(
        self,
        input_: Optional[dict],
        *,
        config: Optional[dict] = None,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> dict:
        thread_id = self._thread_id(config)

        if input_ is None:
            # Resume (Feature 09/ADR-015): load the paused state/node rather
            # than starting fresh from START.
            if self._checkpointer is None or thread_id is None:
                raise ValueError(
                    "invoke(None, ...) resumes a paused thread and requires both "
                    "a checkpointer and a thread_id"
                )
            state, current = self._checkpointer.load(thread_id)
        else:
            state = dict(input_)
            current = self._entry

        steps = 0
        while current != END:
            if steps >= max_steps:
                raise GraphRecursionError(
                    f"Run exceeded max_steps={max_steps} without reaching END — "
                    f"stopped at '{current}'. This is a runaway-loop safety net "
                    "(see Open Question #15), not expected for any well-formed "
                    "Sentinel graph, whose only cycle (grade_documents' retry "
                    "loop) is bounded by its own retry cap."
                )
            steps += 1
            try:
                update = self._nodes[current](state) or {}
            except GraphInterrupt as exc:
                if self._checkpointer is None or thread_id is None:
                    # No way to persist the pause — nothing to resume later,
                    # so propagate rather than silently swallowing it.
                    raise
                self._checkpointer.save(thread_id, state, current)
                return {**state, "__interrupt__": exc.value}
            state.update(update)
            current = self._next(current, state)

        if self._checkpointer is not None and thread_id is not None:
            # Run reached END — nothing left to resume; don't leave a stale
            # checkpoint behind for a completed thread.
            self._checkpointer.clear(thread_id)
        return state


class StateGraph:
    """Stand-in for `langgraph.graph.StateGraph`. Supports linear chains and
    explicit conditional branching (`add_conditional_edges`); does not support
    cycles."""

    def __init__(self, _state_schema: Any):
        self._nodes: dict[str, NodeFn] = {}
        self._static_edges: dict[str, str] = {}
        self._conditional_edges: dict[str, _ConditionalEdge] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: NodeFn) -> None:
        self._nodes[name] = fn

    def _check_no_existing_outgoing_edge(self, from_: str) -> None:
        if from_ in self._static_edges or from_ in self._conditional_edges:
            raise GraphNotLinearError(
                f"Node '{from_}' already has an outgoing edge — each node may have "
                "only one static edge or one conditional-edges call (see Open "
                "Question #15)."
            )

    def add_edge(self, from_: str, to: str) -> None:
        if from_ == START:
            if self._entry is not None:
                raise GraphNotLinearError("Graph already has an entry edge from START.")
            self._entry = to
            return
        self._check_no_existing_outgoing_edge(from_)
        self._static_edges[from_] = to

    def add_conditional_edges(self, from_: str, path: PathFn, path_map: dict[str, str]) -> None:
        if from_ == START:
            raise GraphNotLinearError("Conditional edges cannot originate from START.")
        self._check_no_existing_outgoing_edge(from_)
        self._conditional_edges[from_] = _ConditionalEdge(path=path, path_map=dict(path_map))

    def _all_targets_of(self, node: str) -> list[str]:
        if node in self._conditional_edges:
            return list(self._conditional_edges[node].path_map.values())
        if node in self._static_edges:
            return [self._static_edges[node]]
        return [END]

    def compile(self, *, checkpointer: Optional[Any] = None) -> _CompiledGraph:
        if self._entry is None:
            raise GraphNotLinearError("No edge from START — graph has no entry point.")

        known_nodes = set(self._nodes)
        if self._entry != END and self._entry not in known_nodes:
            raise GraphNotLinearError(f"Entry edge targets unknown node '{self._entry}'.")
        for node_name in known_nodes:
            for target in self._all_targets_of(node_name):
                if target != END and target not in known_nodes:
                    raise GraphNotLinearError(f"Edge targets unknown node '{target}'.")

        # Reachability walk from START across every branch, just to catch an
        # unknown-target edge reachable only via a conditional branch (already
        # checked exhaustively above, but kept as a second pass for any future
        # edge type that isn't exhaustively enumerable that way). Cycles are
        # permitted (Feature 06) — `visited` here is "already validated," not a
        # DFS-stack membership check, so revisiting a node is not an error.
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node == END or node in visited:
                return
            if node not in known_nodes:
                raise GraphNotLinearError(f"Edge targets unknown node '{node}'.")
            visited.add(node)
            for target in self._all_targets_of(node):
                visit(target)

        visit(self._entry)

        return _CompiledGraph(
            entry=self._entry,
            nodes=dict(self._nodes),
            static_edges=dict(self._static_edges),
            conditional_edges=dict(self._conditional_edges),
            checkpointer=checkpointer,
        )
