"""
Sentinel HTTP API (ADR-024 / Open Question #10 resolved).

Two endpoints cover the full HITL lifecycle:

  POST /runs                     — start a new graph run; returns immediately.
                                   If the proposed action is side-effecting the
                                   run pauses at `await_human_approval` and the
                                   response carries `status: "awaiting_approval"`.

  POST /runs/{thread_id}/approve — write a HumanDecision into the paused
                                   checkpoint and resume the graph to completion.

Both endpoints require a running Postgres instance (DATABASE_URL env var) — the
checkpointer and document store auto-configure from that URL at startup via
`get_checkpointer()` and `get_document_store()` (ADR-024 conditional imports).

Startup (lifespan):
  - Calls `checkpointer.setup()` (idempotent — creates LangGraph checkpoint
    tables on first run).
  - Calls `build_graph(checkpointer=checkpointer)` and holds the compiled graph
    in `_state` for the duration of the server's lifetime.

Run with:
  uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload

Or via:
  make serve          (inside Docker, after `make up`)
  scripts/entrypoint.sh serve
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

# FastAPI + Pydantic — required at runtime; imported unconditionally because
# this file is only loaded when the server actually starts (not during
# `make test-local`, which never imports src.api.app).
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.graph.build import build_graph
from src.graph.checkpoint import get_checkpointer
from src.graph.state import HumanDecision


# ---------------------------------------------------------------------------
# Application state (populated during lifespan startup)
# ---------------------------------------------------------------------------

class _AppState:
    graph: Any = None
    checkpointer: Any = None

_state = _AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the graph once at startup; tear down the DB connection at shutdown."""
    database_url = os.environ.get("DATABASE_URL")
    _state.checkpointer = get_checkpointer(database_url)
    _state.checkpointer.setup()  # no-op on InMemoryCheckpointSaver; creates tables on PostgresSaver
    _state.graph = build_graph(checkpointer=_state.checkpointer)
    yield
    # Graceful shutdown: close the psycopg connection if the real checkpointer is wired.
    conn = getattr(_state.checkpointer, "_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


app = FastAPI(
    title="Sentinel SRE Incident Response API",
    description=(
        "LangGraph-backed incident response agent. "
        "POST /runs to start a run; POST /runs/{thread_id}/approve to resume a paused HITL decision."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class StartRunRequest(BaseModel):
    raw_alert: str
    thread_id: Optional[str] = None  # auto-generated if omitted


class StartRunResponse(BaseModel):
    thread_id: str
    status: str  # "complete" | "awaiting_approval" | "rejected"
    proposed_action: Optional[dict] = None
    result: Optional[dict] = None


class ApprovalRequest(BaseModel):
    approved: bool
    modified_action: Optional[dict] = None
    note: str = ""


class ApprovalResponse(BaseModel):
    thread_id: str
    status: str  # always "complete"
    result: dict


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/runs", response_model=StartRunResponse)
def start_run(req: StartRunRequest) -> StartRunResponse:
    """Start a new incident-response graph run.

    The graph runs synchronously to completion or to the first
    `await_human_approval` interrupt (for side-effecting proposed actions).
    Returns immediately in both cases; the caller polls or listens for
    completion (a GET /runs/{thread_id} endpoint is on the roadmap).

    Supply `thread_id` to use a caller-controlled identifier (e.g. a ticket
    ID). Omit it to receive an auto-generated UUID.
    """
    thread_id = req.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "raw_alert": req.raw_alert,
        "thread_id": thread_id,
        "guardrail_input_verdict": None,
        "guardrail_output_verdict": None,
        "rejection_reason": None,
        "route": None,
        "retrieved_docs": [],
        "reranked_docs": [],
        "relevance_grade": None,
        "retry_count": 0,
        "current_query": None,
        "diagnosis": None,
        "proposed_action": None,
        "diagnosis_confidence": None,
        "human_decision": None,
        "execution_result": None,
        "postmortem_draft": None,
    }

    try:
        result = _state.graph.invoke(initial_state, config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # The shim raises GraphInterrupt; real langgraph stores it in result["__interrupt__"].
    paused = isinstance(result, dict) and "__interrupt__" in result
    rejected = isinstance(result, dict) and result.get("rejection_reason") is not None

    status = "awaiting_approval" if paused else ("rejected" if rejected else "complete")

    return StartRunResponse(
        thread_id=thread_id,
        status=status,
        proposed_action=result.get("proposed_action") if isinstance(result, dict) else None,
        result=result if (not paused and isinstance(result, dict)) else None,
    )


@app.post("/runs/{thread_id}/approve", response_model=ApprovalResponse)
def submit_approval(thread_id: str, req: ApprovalRequest) -> ApprovalResponse:
    """Submit a human approval or rejection for a paused run.

    Writes `HumanDecision` into the checkpointed state, then resumes the
    graph from `await_human_approval`. On approval, execution proceeds to
    the `execute` node; on rejection, the graph re-enters `diagnose`.

    Raises 404 if `thread_id` is not found in the checkpointer (thread was
    never started, or already completed and cleared).
    """
    config = {"configurable": {"thread_id": thread_id}}

    decision: HumanDecision = {
        "approved": req.approved,
        "modified_action": req.modified_action,
        "note": req.note,
    }

    try:
        _state.graph.update_state(config, {"human_decision": decision})
        result = _state.graph.invoke(None, config=config)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"thread_id {thread_id!r} not found — run may have already completed or was never started.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ApprovalResponse(
        thread_id=thread_id,
        status="complete",
        result=result if isinstance(result, dict) else {},
    )


# ---------------------------------------------------------------------------
# Health check (used by docker-compose healthcheck, load balancers)
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz() -> Dict[str, str]:
    """Liveness probe. Returns 200 once the server is up and the graph is built."""
    if _state.graph is None:
        raise HTTPException(status_code=503, detail="graph not yet initialized")
    return {"status": "ok"}
