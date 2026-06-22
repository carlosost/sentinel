"""
`IncidentState` — the single shared state schema threaded through every graph node.

This is the *initial* Phase 1 shape (ADR-007/Feature 01). It is amended additively by
later features as their ADRs specify — see PROJECT_MEMORY.md §5.1 for the cumulative,
canonical contract and which ADR introduced/amended each field. Each amendment is
applied here as its corresponding feature is implemented, with a comment pointing at
the ADR responsible, so this file's history mirrors the PMA's.
"""

from __future__ import annotations

from typing import Literal, Optional, TypedDict


class IncidentState(TypedDict):
    raw_alert: str

    # Pillar 3 (Guardrails) hook output — stubbed verdict until Feature 13/ADR-019.
    guardrail_input_verdict: Optional[dict]
    guardrail_output_verdict: Optional[dict]

    # Pillar 1 (Advanced RAG) — populated by router/retriever/reranker/grade_documents
    # once those features land (roadmap items 4-6).
    route: Optional[Literal["runbooks", "postmortems", "infra_code_docs"]]
    retrieved_docs: list[dict]
    reranked_docs: list[dict]
    relevance_grade: Optional[float]
    retry_count: int

    # Pillar 1 (generation) — populated by diagnose/propose_action (roadmap item 7).
    diagnosis: Optional[str]
    proposed_action: Optional[dict]

    # Pillar 2 (HITL) — populated once await_human_approval/execute land (items 9-10).
    human_decision: Optional[dict]
    execution_result: Optional[dict]

    # Final reporting step (roadmap item 11).
    postmortem_draft: Optional[str]

    # Durable-run identifier for the Postgres checkpointer (ADR-002).
    thread_id: str
