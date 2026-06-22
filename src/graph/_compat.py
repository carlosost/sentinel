"""
Minimal stdlib stand-in for the slice of `langgraph.graph` Sentinel currently uses.

SANDBOX NOTE (ADR-021): this dev sandbox has no PyPI egress, so the real `langgraph`
package is not installable here. This shim implements only `START`/`END` sentinels
and a `StateGraph` supporting linear `add_node`/`add_edge`/`compile()`/`invoke()` —
enough for Feature 01's `entry -> END` graph and any purely-linear chain added by
near-term features.

It deliberately does NOT support conditional edges, cycles, or `interrupt()`/durable
checkpointing — those are required starting around Feature 04 (router branching),
Feature 06 (self-RAG retry loop), and Feature 09 (HITL interrupt/resume). Open
Question #15 tracks replacing this shim with real `langgraph` (and, with it,
re-verifying every node wired against it) before any feature that needs those
capabilities ships its "real" implementation. Until then, this shim itself is the
known limiting factor on how much of the roadmap can be faithfully executed here.
"""

from __future__ import annotations

from typing import Any, Callable

START = "__start__"
END = "__end__"

NodeFn = Callable[[dict], dict]


class GraphNotLinearError(RuntimeError):
    """Raised when a graph uses a feature (branching, cycles) this shim can't run."""


class _CompiledGraph:
    def __init__(self, order: list[str], nodes: dict[str, NodeFn]):
        self._order = order
        self._nodes = nodes

    def invoke(self, initial_state: dict) -> dict:
        state: dict[str, Any] = dict(initial_state)
        for name in self._order:
            update = self._nodes[name](state) or {}
            state.update(update)
        return state


class StateGraph:
    """Stand-in for `langgraph.graph.StateGraph`. Strictly linear: each node must
    have exactly one outgoing edge, ending at END, with no branches or cycles."""

    def __init__(self, _state_schema: Any):
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}
        self._entry: str | None = None

    def add_node(self, name: str, fn: NodeFn) -> None:
        self._nodes[name] = fn

    def add_edge(self, from_: str, to: str) -> None:
        if from_ == START:
            self._entry = to
            return
        if from_ in self._edges:
            raise GraphNotLinearError(
                f"Node '{from_}' already has an outgoing edge — this shim does not "
                "support branching (see Open Question #15)."
            )
        self._edges[from_] = to

    def compile(self) -> _CompiledGraph:
        if self._entry is None:
            raise GraphNotLinearError("No edge from START — graph has no entry point.")
        order: list[str] = []
        current = self._entry
        seen: set[str] = set()
        while current != END:
            if current in seen:
                raise GraphNotLinearError(
                    f"Cycle detected at '{current}' — this shim does not support "
                    "cycles (see Open Question #15)."
                )
            seen.add(current)
            order.append(current)
            current = self._edges.get(current, END)
        return _CompiledGraph(order, dict(self._nodes))
