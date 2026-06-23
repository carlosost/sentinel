"""
Graph assembly (ADR-001, ADR-007, ADR-009, ADR-010).

v1 (Feature 01) was `entry -> END` — a placeholder so the schema and wiring exist
before any real node is built. Feature 03 (ADR-009) replaced that placeholder with
the first real node, `guardrail_input`, which conditionally routes to `reject` (on
an unsafe verdict) or `router` (otherwise). Feature 04 (ADR-010) replaced the
`router` placeholder with the real node: it classifies the alert into exactly one
corpus and writes `state.route`. Feature 05 (ADR-011) replaced `_retriever_placeholder`
with the real `retriever` and `reranker` nodes: top-k=20 cosine-similarity search
against the routed corpus, then cross-encoder re-ranking to top-k=5. Feature 06
(ADR-012) replaces `_grade_documents_placeholder` with the real `grade_documents`
node and introduces the graph's first real cycle:
`grade_documents -(low relevance, retry budget remaining)-> router`, bounded by
`grade_documents`' own retry cap (never by `_compat.py`'s runtime safety net — see
that module's docstring). `diagnose` itself doesn't exist yet (roadmap item 7) —
`_diagnose_placeholder` stands in for it, the same placeholder role
`_grade_documents_placeholder` played here until this feature. The Postgres
checkpointer (ADR-002) is not wired in yet: per ADR-015/Feature 09, that wiring
happens once `await_human_approval` exists and there is an actual interrupt
boundary to persist across. Until then the graph compiles with no checkpointer
(in-process only).

SANDBOX NOTE (ADR-021): imports a stdlib shim (`src/graph/_compat.py`) in place of
real `langgraph`, since this sandbox has no PyPI egress. The shim now supports
linear chains, conditional branching, and cycles (Feature 06 addendum) — it still
does not support `interrupt()`/durable checkpointing, needed starting Feature 09.
See `_compat.py`'s docstring and Open Question #15.
"""

from __future__ import annotations

from src.graph._compat import END, START, StateGraph
from src.graph.nodes.grade_documents import (
    ROUTE_PROCEED,
    ROUTE_RETRY,
    grade_documents,
    grade_documents_route,
)
from src.graph.nodes.guardrail_input import (
    ROUTE_SAFE,
    ROUTE_UNSAFE,
    guardrail_input,
    guardrail_input_route,
)
from src.graph.nodes.reject import reject
from src.graph.nodes.reranker import reranker
from src.graph.nodes.retriever import retriever
from src.graph.nodes.router import router
from src.graph.state import IncidentState


def _diagnose_placeholder(state: IncidentState) -> dict:
    """Placeholder for the `diagnose` node (roadmap item 7 / Feature 07). Routes
    straight to END until root-cause diagnosis + remediation proposal exist."""
    return {}


def build_graph() -> StateGraph:
    """Construct and compile the Sentinel graph for the current feature set."""
    graph = StateGraph(IncidentState)

    graph.add_node("guardrail_input", guardrail_input)
    graph.add_node("reject", reject)
    graph.add_node("router", router)
    graph.add_node("retriever", retriever)
    graph.add_node("reranker", reranker)
    graph.add_node("grade_documents", grade_documents)
    graph.add_node("diagnose", _diagnose_placeholder)

    graph.add_edge(START, "guardrail_input")
    graph.add_conditional_edges(
        "guardrail_input",
        guardrail_input_route,
        {ROUTE_SAFE: "router", ROUTE_UNSAFE: "reject"},
    )
    graph.add_edge("reject", END)
    graph.add_edge("router", "retriever")
    graph.add_edge("retriever", "reranker")
    graph.add_edge("reranker", "grade_documents")
    graph.add_conditional_edges(
        "grade_documents",
        grade_documents_route,
        {ROUTE_RETRY: "router", ROUTE_PROCEED: "diagnose"},
    )
    graph.add_edge("diagnose", END)

    return graph.compile()
