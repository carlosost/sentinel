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
  - `compile()` performs a static reachability walk from `START` across every
    possible branch (not just one path) and raises `GraphNotLinearError` if it
    finds a cycle. Branching is supported; cycles are not.

It still deliberately does NOT support cycles or `interrupt()`/durable
checkpointing — those are required starting around Feature 06 (self-RAG retry
loop) and Feature 09 (HITL interrupt/resume). Open Question #15 tracks replacing
this shim with real `langgraph` (and, with it, re-verifying every node wired
against it) before any feature that needs those capabilities ships its "real"
implementation. Until then, this shim itself is the known limiting factor on how
much of the roadmap can be faithfully executed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

START = "__start__"
END = "__end__"

NodeFn = Callable[[dict], dict]
PathFn = Callable[[dict], str]


class GraphNotLinearError(RuntimeError):
    """Raised when a graph uses a feature (cycles) this shim can't run, or when an
    edge is malformed (duplicate outgoing edge, unknown target, missing entry)."""


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

    def invoke(self, initial_state: dict) -> dict:
        state: dict[str, Any] = dict(initial_state)
        current = self._entry
        visited_this_run: set[str] = set()
        while current != END:
            if current in visited_this_run:
                # Compile-time DFS should already have caught any cycle; this is a
                # defensive backstop in case a path function's behavior depends on
                # runtime state in a way the static walk couldn't see.
                raise GraphNotLinearError(
                    f"Cycle encountered at runtime at '{current}' — this shim does "
                    "not support cycles (see Open Question #15)."
                )
            visited_this_run.add(current)
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

        # Static reachability walk from START across every branch, detecting cycles
        # via the DFS-stack ("currently being visited") convention.
        on_stack: set[str] = set()

        def visit(node: str) -> None:
            if node == END:
                return
            if node not in known_nodes:
                raise GraphNotLinearError(f"Edge targets unknown node '{node}'.")
            if node in on_stack:
                raise GraphNotLinearError(
                    f"Cycle detected at '{node}' — this shim does not support "
                    "cycles (see Open Question #15)."
                )
            on_stack.add(node)
            for target in self._all_targets_of(node):
                visit(target)
            on_stack.discard(node)

        visit(self._entry)

        return _CompiledGraph(
            entry=self._entry,
            nodes=dict(self._nodes),
            static_edges=dict(self._static_edges),
            conditional_edges=dict(self._conditional_edges),
        )
