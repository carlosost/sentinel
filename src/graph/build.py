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
(ADR-012) replaced `_grade_documents_placeholder` with the real `grade_documents`
node and introduced the graph's first real cycle:
`grade_documents -(low relevance, retry budget remaining)-> router`, bounded by
`grade_documents`' own retry cap (never by `_compat.py`'s runtime safety net — see
that module's docstring). Feature 07 (ADR-013) replaces `_diagnose_placeholder`
with the real `diagnose` and `propose_action` nodes: `diagnose` produces a root-
cause diagnosis plus a `diagnosis_confidence` hedge signal, and `propose_action`
produces a registry-validated (`src/tools/registry.py`) `{tool, args,
side_effecting}` proposal. Feature 08 (ADR-014) replaces
`_guardrail_output_placeholder` with the real `guardrail_output` node: one
node/routing-function pair reused at the pre-execution call site now wired
(`propose_action -> guardrail_output -(unsafe)-> reject`,
`-(safe, side-effecting)-> await_human_approval`, `-(safe, read-only)->
execute`) and, per ADR-014, the future post-execution call site
(`write_postmortem -> guardrail_output`, roadmap item 11) the same function
already supports by branching on `execution_result`. Feature 09 (ADR-015)
replaces `_await_human_approval_placeholder` with the real
`await_human_approval` node: it interrupts (pauses + persists via the
checkpointer) until `state.human_decision` is set, then conditionally routes
`-(approved)-> execute`, `-(rejected)-> diagnose` (the diagnose re-entry Open
Question #9 partially de-risks — the edge exists, `diagnose`'s own behavior on
re-entry is unchanged/unscoped). Feature 10 (ADR-016) replaces
`_execute_placeholder` with the real `execute` node: it dispatches the
resolved action (ADR-015's `modified_action` precedence, via
`await_human_approval.resolve_action`, when a human decision exists;
otherwise `proposed_action` unchanged for the read-only branch) to
`src.tools.executors.execute_tool` against the mock staging API, then
conditionally routes `-(success)-> write_postmortem`, `-(failure)->
diagnose`. `write_postmortem` doesn't exist yet (roadmap item 11) —
`_write_postmortem_placeholder` stands in for it. `build_graph()` now
takes an optional `checkpointer` (see `src/graph/checkpoint.py`'s
`InMemoryCheckpointSaver`, the sandbox stand-in for `PostgresSaver` per
ADR-002/015); omitting it preserves every prior feature's behavior exactly
(an uncaught interrupt simply propagates, since there's nowhere to persist
it) — only call sites that actually need pause/resume must pass one.

SANDBOX NOTE (ADR-021): imports a stdlib shim (`src/graph/_compat.py`) in place of
real `langgraph`, since this sandbox has no PyPI egress. The shim now supports
linear chains, conditional branching, cycles (Feature 06 addendum), and, as of
Feature 09, `interrupt()`/checkpointed pause-resume (see `_compat.py`'s ADDENDUM
docstring and Open Question #15 for exactly what's still not faithfully modeled).
"""

from __future__ import annotations

from typing import Optional

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
from src.graph.nodes.diagnose import diagnose
from src.graph.nodes.await_human_approval import (
    ROUTE_APPROVED,
    ROUTE_REJECTED,
    await_human_approval,
    await_human_approval_route,
)
from src.graph.nodes.execute import ROUTE_FAILURE, ROUTE_SUCCESS, execute, execute_route
from src.graph.nodes.guardrail_output import (
    ROUTE_AWAIT_APPROVAL,
    ROUTE_EXECUTE,
    ROUTE_REJECT,
    ROUTE_END as GUARDRAIL_OUTPUT_ROUTE_END,
    guardrail_output,
    guardrail_output_route,
)
from src.graph.nodes.propose_action import propose_action
from src.graph.nodes.reject import reject
from src.graph.nodes.reranker import reranker
from src.graph.nodes.retriever import retriever
from src.graph.nodes.router import router
from src.graph.state import IncidentState


def _write_postmortem_placeholder(state: IncidentState) -> dict:
    """Placeholder for the `write_postmortem` node (roadmap item 11 / Feature
    11). Routes straight to END until the postmortem draft and the
    post-execution `guardrail_output` call site exist."""
    return {}


def build_graph(checkpointer: Optional[object] = None) -> StateGraph:
    """Construct and compile the Sentinel graph for the current feature set.

    `checkpointer` (Feature 09/ADR-015) is the sandbox `InMemoryCheckpointSaver`
    stand-in for `PostgresSaver` — pass the same instance across separate
    `build_graph()` calls to simulate resuming a paused thread after a process
    restart (see `tests/graph/test_hitl_checkpoint_restart.py`). Omitted by
    default so every pre-Feature-09 caller/test is unaffected.
    """
    graph = StateGraph(IncidentState)

    graph.add_node("guardrail_input", guardrail_input)
    graph.add_node("reject", reject)
    graph.add_node("router", router)
    graph.add_node("retriever", retriever)
    graph.add_node("reranker", reranker)
    graph.add_node("grade_documents", grade_documents)
    graph.add_node("diagnose", diagnose)
    graph.add_node("propose_action", propose_action)
    graph.add_node("guardrail_output", guardrail_output)
    graph.add_node("await_human_approval", await_human_approval)
    graph.add_node("execute", execute)
    graph.add_node("write_postmortem", _write_postmortem_placeholder)

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
    graph.add_edge("diagnose", "propose_action")
    graph.add_edge("propose_action", "guardrail_output")
    graph.add_conditional_edges(
        "guardrail_output",
        guardrail_output_route,
        {
            ROUTE_REJECT: "reject",
            ROUTE_AWAIT_APPROVAL: "await_human_approval",
            ROUTE_EXECUTE: "execute",
            GUARDRAIL_OUTPUT_ROUTE_END: END,
        },
    )
    graph.add_conditional_edges(
        "await_human_approval",
        await_human_approval_route,
        {ROUTE_APPROVED: "execute", ROUTE_REJECTED: "diagnose"},
    )
    graph.add_conditional_edges(
        "execute",
        execute_route,
        {ROUTE_SUCCESS: "write_postmortem", ROUTE_FAILURE: "diagnose"},
    )
    graph.add_edge("write_postmortem", END)

    return graph.compile(checkpointer=checkpointer)
