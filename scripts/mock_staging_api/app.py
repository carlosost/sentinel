"""
Mock staging API (ADR-016, ADR-024).

Accepts POST /execute with {tool, args} and returns {success, output, error}.
This service exists purely as a realistic async boundary for the `execute` node —
it simulates tool dispatch without touching production systems.

Every known tool (from src/tools/registry.py) returns a canned success response.
Unknown tools return success=False with an explanatory error (matching the registry's
own behavior: the `execute` node validates against the registry before calling this
service, so an unknown-tool response here would only appear if the registry drifted).

Run standalone: uvicorn scripts.mock_staging_api.app:app --port 8001
Run via Docker: docker compose up mock-staging-api
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Sentinel Mock Staging API", version="0.1.0")

# Canned responses keyed by tool name — expand as the tool registry grows.
_MOCK_RESPONSES: Dict[str, Dict[str, Any]] = {
    "restart_service": {"success": True, "output": "Service restarted successfully (mock)."},
    "scale_deployment": {"success": True, "output": "Deployment scaled to requested replica count (mock)."},
    "rollback_deployment": {"success": True, "output": "Deployment rolled back to previous revision (mock)."},
    "drain_node": {"success": True, "output": "Node drained and cordoned (mock)."},
    "get_logs": {"success": True, "output": "Log lines returned (mock): [INFO] Service healthy."},
    "describe_pod": {"success": True, "output": "Pod description returned (mock): status=Running."},
    "get_metrics": {"success": True, "output": "Metrics returned (mock): cpu=12%, mem=34%."},
}


class ExecuteRequest(BaseModel):
    tool: str
    args: Dict[str, Any]


class ExecuteResponse(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None


@app.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest) -> ExecuteResponse:
    response = _MOCK_RESPONSES.get(req.tool)
    if response is None:
        return ExecuteResponse(
            success=False,
            output="",
            error=f"Unknown tool: {req.tool!r}. Not in mock registry.",
        )
    return ExecuteResponse(**response)


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}
