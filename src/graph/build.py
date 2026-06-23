"""
Graph assembly (ADR-001, ADR-007, ADR-009, ADR-010).

v1 (Feature 01) was `entry -> END` — a placeholder so the schema and wiring exist
before any real node is built. Feature 03 (ADR-009) replaced that placeholder with
the first real node, `guardrail_input`, which conditionally routes to `reject` (on
an unsafe verdict) or `router` (otherwise). Feature 04 (ADR-010) replaces the
`router` placeholder with the real node: it classifies the alert into exactly one
corpus and writes `state.route`. `retriever` itself doesn't exist yet (roadmap
item 5) — `_retriever_placeholder` stands in for it, the same role
`_router_placeholder` played here until this feature, so the graph stays
compilable end-to-end as each feature lands. The Postgres checkpointer (ADR-002)
is not wired in yet: per ADR-015/Feature 09, that wiring happens once
`await_human_approval` exists and there is an actual interrupt boundary to
persist across. Until then the graph compiles with no checkpointer (in-process
only).

SANDBOX NOTE (ADR-021): imports a stdlib shim (`src/graph/_compat.py`) in place of
real `langgraph`, since this sandbox has no PyPI egress. The shim supports linear
chains and explicit conditional branching (`add_conditional_edges`) but not
cycles — see its docstring and Open Question #15 for what still breaks once
cycles/interrupts are needed (Features 06, 09).
"""

from __future__ import annotations

from src.graph._compat import END, START, StateGraph
from src.graph.nodes.guardrail_input import (
    ROUTE_SAFE,
    ROUTE_UNSAFE,
    guardrail_input,
    guardrail_input_route,
)
from src.graph.nodes.reject import reject
from src.graph.nodes.router import router
from src.graph.state import IncidentState


def _retriever_placeholder(state: IncidentState) -> dict:
    """Placeholder for the `retriever` node (roadmap item 5 / Feature 05). Routes
    straight to END until vector retrieval is implemented."""
    return {}


def build_graph() -> StateGraph:
    """Construct and compile the Sentinel graph for the current feature set."""
    graph = StateGraph(IncidentState)

    graph.add_node("guardrail_input", guardrail_input)
    graph.add_node("reject", reject)
    graph.add_node("router", router)
    graph.add_node("retriever", _retriever_placeholder)

    graph.add_edge(START, "guardrail_input")
    graph.add_conditional_edges(
        "guardrail_input",
        guardrail_input_route,
        {ROUTE_SAFE: "router", ROUTE_UNSAFE: "reject"},
    )
    graph.add_edge("reject", END)
    graph.add_edge("router", "retriever")
    graph.add_edge("retriever", END)

    return graph.compile()
