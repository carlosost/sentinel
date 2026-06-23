"""
Tool executors (ADR-016): dispatch a resolved `{tool, args}` action to the
mock staging API and normalize its response into `execution_result`'s pinned
shape: `{"tool": str, "args": dict, "success": bool, "output": str, "error":
Optional[str]}`.

SANDBOX NOTE (ADR-021 addendum, Feature 10): ADR-016 specifies a real
`mock-staging-api` docker-compose service (`infra/docker-compose.yml`) that
`execute` calls via `httpx`. This sandbox has neither a Docker daemon nor
`httpx` (no PyPI egress) to run/call it, so `get_staging_api_client()` below
follows the same factory pattern as `src.gateway.client_factory`: a stdlib
stand-in (`_StagingApiClient`) whose `.call()` raises `NotImplementedError`
on the real network call. Tests monkeypatch `get_staging_api_client` exactly
like `get_chat_client`/`get_embedding_client` are patched elsewhere — see
`tests/graph/nodes/test_execute.py`. Open Question #15 tracks swapping this
for a real `httpx`-backed client once this runs somewhere with Docker/PyPI
access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from src.tools.registry import UnknownToolError, get_tool_spec


class ExecutorError(RuntimeError):
    """Raised when asked to execute a tool absent from the registry — never
    silently dispatched as if it might succeed, the same "never silently
    default" discipline as `RouterError`/`ProposeActionError`."""


@dataclass
class _StagingApiClient:
    """Stand-in for an `httpx`-backed client against `mock-staging-api`
    (ADR-021 addendum)."""

    base_url: str = "http://mock-staging-api"

    def call(self, tool: str, args: dict) -> dict:  # pragma: no cover
        raise NotImplementedError(
            "Real staging-API calls require a live mock-staging-api service and "
            "httpx (Open Question #15); not available in this sandbox."
        )


def get_staging_api_client() -> _StagingApiClient:
    """Sole construction path for the staging-API client (mirrors
    `client_factory.get_chat_client`'s role for model clients) — tests patch
    this function, never `_StagingApiClient` directly."""
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
