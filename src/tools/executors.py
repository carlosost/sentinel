"""
Tool executors (ADR-016, ADR-024): dispatch a resolved `{tool, args}` action to
the mock staging API and normalize its response into `execution_result`'s pinned
shape: `{"tool": str, "args": dict, "success": bool, "output": str, "error":
Optional[str]}`.

ADR-024 (Production Readiness): `get_staging_api_client()` now returns a real
`_HttpxStagingApiClient` when `httpx` is installed, falling back to the
`_StagingApiClient` shim (ADR-021) otherwise. The mock-staging-api docker-compose
service exposes the staging endpoint at `http://mock-staging-api`. Tests
monkeypatch `get_staging_api_client` at the node's import path — unaffected by
this change, since the seam is the factory function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.tools.registry import UnknownToolError, get_tool_spec

# Real httpx — used when installed (ADR-024).
try:
    import httpx as _httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

_DEFAULT_BASE_URL = "http://mock-staging-api"


class ExecutorError(RuntimeError):
    """Raised when asked to execute a tool absent from the registry — never
    silently dispatched as if it might succeed, the same "never silently
    default" discipline as `RouterError`/`ProposeActionError`."""


@dataclass
class _StagingApiClient:
    """Stdlib shim for an `httpx`-backed client against `mock-staging-api`
    (ADR-021). Used automatically when httpx is not installed."""

    base_url: str = _DEFAULT_BASE_URL

    def call(self, tool: str, args: dict) -> dict:  # pragma: no cover
        raise NotImplementedError(
            "Real staging-API calls require a live mock-staging-api service and "
            "httpx (install it and start the service via `make up`)."
        )


@dataclass
class _HttpxStagingApiClient:
    """Real httpx-backed client against the mock-staging-api docker service
    (ADR-016, ADR-024). Used when httpx is installed."""

    base_url: str = _DEFAULT_BASE_URL
    timeout: float = 10.0

    def call(self, tool: str, args: dict) -> dict:
        response = _httpx.post(
            f"{self.base_url}/execute",
            json={"tool": tool, "args": args},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


def get_staging_api_client():
    """Return the appropriate staging-API client for the current environment.

    Returns a real `_HttpxStagingApiClient` when httpx is installed; falls back
    to the `_StagingApiClient` shim otherwise. Tests patch this function at the
    node's import path — never instantiate the client class directly.
    """
    if _HTTPX_AVAILABLE:
        return _HttpxStagingApiClient()
    return _StagingApiClient()


def execute_tool(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch `tool`/`args` to the staging API client and normalize the
    response into `execution_result`'s ADR-016 shape.

    An unknown tool is a hard error (`ExecutorError`) raised before any call
    is attempted — never silently treated as a successful or failed
    execution. A raised exception from the client itself (a real network
    failure, in production) is normalized into `execution_result.success =
    False` rather than propagated, since a staging-API outage routing back to
    `diagnose` is the correct, designed behavior (ADR-016's failure-routing
    path), not a graph-crashing error.
    """
    try:
        get_tool_spec(tool)
    except UnknownToolError as exc:
        raise ExecutorError(str(exc)) from exc

    client = get_staging_api_client()
    try:
        response = client.call(tool, args)
    except Exception as exc:  # noqa: BLE001 - normalized into execution_result, not raised
        return {"tool": tool, "args": args, "success": False, "output": "", "error": str(exc)}

    return {
        "tool": tool,
        "args": args,
        "success": bool(response.get("success", False)),
        "output": response.get("output", ""),
        "error": response.get("error"),
    }
