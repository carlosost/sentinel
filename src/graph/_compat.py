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

It still deliberately does NOT support `interrupt()`/durable checkpointing —
required starting around Feature 09 (HITL interrupt/resume). Open Question #15
tracks replacing this shim with real `langgraph` (and, with it, re-verifying every
node wired against it) before any feature that needs that capability ships its
"real" implementation. Until then, this shim itself is the known limiting factor on
how much of the roadmap can be faithfully executed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

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
    ):
        self._entry = entry
        self._nodes = nodes
        self._static_edges = static_edges
        self._conditional_edges = conditional_edges

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

    def invoke(self, initial_state: dict, *, max_steps: int = DEFAULT_MAX_STEPS) -> dict:
        state: dict[str, Any] = dict(initial_state)
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
            update = self._nodes[current](state) or {}
            state.update(update)
            current = self._next(current, state)
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

    def compile(self) -> _CompiledGraph:
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
        )
