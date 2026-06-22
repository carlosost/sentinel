"""
Graph assembly (ADR-001, ADR-007).

v1 (Feature 01): just `entry -> END` — a placeholder so the schema and wiring exist
before any real node is built. Each subsequent feature adds its node(s) and edges
here. The Postgres checkpointer (ADR-002) is not wired in yet: per ADR-015/Feature 09,
that wiring happens once `await_human_approval` exists and there is an actual
interrupt boundary to persist across. Until then the graph compiles with no
checkpointer (in-process only).

SANDBOX NOTE (ADR-021): imports a stdlib shim (`src/graph/_compat.py`) in place of
real `langgraph`, since this sandbox has no PyPI egress. The shim only supports
linear graphs — see its docstring and Open Question #15 for what breaks once
branching/cycles/interrupts are needed (Features 04, 06, 09).
"""

from __future__ import annotations

from src.graph._compat import END, START, StateGraph
from src.graph.state import IncidentState


def _entry(state: IncidentState) -> dict:
    """Placeholder entry node. Real nodes (guardrail_input, etc.) replace this as
    their features land."""
    return {}


def build_graph() -> StateGraph:
    """Construct and compile the Sentinel graph for the current feature set."""
    graph = StateGraph(IncidentState)
    graph.add_node("entry", _entry)
    graph.add_edge(START, "entry")
    graph.add_edge("entry", END)
    return graph.compile()
