"""
Sentinel HTTP API (ADR-024 / Open Question #10 resolved).

Three endpoints cover the full HITL lifecycle:

  POST /runs                     — start a new graph run; returns immediately.
                                   Graph execution runs in a thread pool so the
                                   event loop is never blocked. If the proposed
                                   action is side-effecting the run pauses at
                                   `await_human_approval` and the response
                                   carries `status: "awaiting_approval"`.

  GET  /runs/{thread_id}         — poll for run status. Returns the last known
                                   state from the in-memory run store. Useful
                                   when the client wants to poll rather than
                                   wait for the POST to return.

  POST /runs/{thread_id}/approve — write a HumanDecision into the paused
                                   checkpoint and resume the graph to completion.

All endpoints require a running Postgres instance (DATABASE_URL env var) — the
checkpointer and document store auto-configure from that URL at startup via
`get_checkpointer()` and `get_document_store()` (ADR-024 conditional imports).

Startup (lifespan):
  - Calls `checkpointer.setup()` (idempotent — creates LangGraph checkpoint
    tables on first run).
  - Calls `build_graph(checkpointer=checkpointer)` and holds the compiled graph
    in `_state` for the duration of the server's lifetime.

Timeout:
  Graph execution is bounded by GRAPH_TIMEOUT_SECONDS (default 120). A 504
  is returned if the graph does not complete within that window.

Run with:
  uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload

Or via:
  make serve          (inside Docker, after `make up`)
  scripts/entrypoint.sh serve
"""

from __future__ import annotations

import asyncio
import functools
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

# Configurable graph execution timeout (seconds). Override via env var.
_GRAPH_TIMEOUT = float(os.environ.get("GRAPH_TIMEOUT_SECONDS", "120"))


# ---------------------------------------------------------------------------
# Application state (populated during lifespan startup)
# ---------------------------------------------------------------------------

class _AppState:
    graph: Any = None
    checkpointer: Any = None

_state = _AppState()

# In-memory run status store: thread_id -> status dict.
# Keyed by thread_id; values are the last known StartRunResponse payload.
# Not persisted across server restarts — the checkpointer holds durable state.
_run_store: Dict[str, dict] = {}


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
        "POST /runs to start a run; GET /runs/{thread_id} to poll status; "
        "POST /runs/{thread_id}/approve to resume a paused HITL decision."
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


class RunStatusResponse(BaseModel):
    thread_id: str
    status: str  # "complete" | "awaiting_approval" | "rejected" | "running" | "not_found"
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
async def start_run(req: StartRunRequest) -> StartRunResponse:
    """Start a new incident-response graph run.

    Graph execution runs in a thread pool (asyncio.to_thread) so the server
    event loop stays responsive during long model calls. The call blocks until
    the graph completes or reaches `await_human_approval`. A 504 is returned
    if execution exceeds GRAPH_TIMEOUT_SECONDS (default 120 s).

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

    # Mark as running so GET /runs/{thread_id} can report status immediately.
    _run_store[thread_id] = {"status": "running", "proposed_action": None, "result": None}

    try:
        invoke_fn = functools.partial(_state.graph.invoke, initial_state, config=config)
        result = await asyncio.wait_for(
            asyncio.to_thread(invoke_fn),
            timeout=_GRAPH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        _run_store[thread_id] = {"status": "timeout", "proposed_action": None, "result": None}
        raise HTTPException(
            status_code=504,
            detail=f"Graph execution timed out after {_GRAPH_TIMEOUT:.0f}s",
        )
    except Exception as exc:
        _run_store[thread_id] = {"status": "error", "proposed_action": None, "result": None}
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # The shim raises GraphInterrupt; real langgraph stores it in result["__interrupt__"].
    paused = isinstance(result, dict) and "__interrupt__" in result
    rejected = isinstance(result, dict) and result.get("rejection_reason") is not None

    status = "awaiting_approval" if paused else ("rejected" if rejected else "complete")
    proposed_action = result.get("proposed_action") if isinstance(result, dict) else None
    run_result = result if (not paused and isinstance(result, dict)) else None

    _run_store[thread_id] = {
        "status": status,
        "proposed_action": proposed_action,
        "result": run_result,
    }

    return StartRunResponse(
        thread_id=thread_id,
        status=status,
        proposed_action=proposed_action,
        result=run_result,
    )


@app.get("/runs/{thread_id}", response_model=RunStatusResponse)
async def get_run_status(thread_id: str) -> RunStatusResponse:
    """Poll the status of a run by thread_id.

    Returns the last known status from the in-memory run store. If the run
    is still executing, status is "running". If the thread_id is unknown
    (never started or server was restarted), status is "not_found".

    Note: this store is in-memory only — it does not survive server restarts.
    For durable state, query the checkpointer directly.
    """
    entry = _run_store.get(thread_id)
    if entry is None:
        return RunStatusResponse(thread_id=thread_id, status="not_found")
    return RunStatusResponse(
        thread_id=thread_id,
        status=entry["status"],
        proposed_action=entry.get("proposed_action"),
        result=entry.get("result"),
    )


@app.post("/runs/{thread_id}/approve", response_model=ApprovalResponse)
async def submit_approval(thread_id: str, req: ApprovalRequest) -> ApprovalResponse:
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
        resume_fn = functools.partial(_state.graph.invoke, None, config=config)
        result = await asyncio.wait_for(
            asyncio.to_thread(resume_fn),
            timeout=_GRAPH_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Graph resume timed out after {_GRAPH_TIMEOUT:.0f}s",
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"thread_id {thread_id!r} not found — run may have already completed or was never started.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    run_result = result if isinstance(result, dict) else {}
    _run_store[thread_id] = {"status": "complete", "proposed_action": None, "result": run_result}

    return ApprovalResponse(
        thread_id=thread_id,
        status="complete",
        result=run_result,
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
