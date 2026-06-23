# Infra Doc: mock-staging-api

`mock-staging-api` (ADR-016) is the only execution target for Sentinel's
remediation tools in v1 — `restart_service`, `rollback_deploy`,
`page_secondary_oncall`, and `fetch_additional_logs` all dispatch HTTP calls
to this service rather than any real production infrastructure.

**Endpoints:** one endpoint per registered tool name (`POST
/tools/restart_service`, etc.), each accepting the tool's `args` dict and
returning `{"success": bool, "output": str, "error": Optional[str]}` —
mirroring `execution_result`'s shape minus the `tool`/`args` echo, which
`execute` attaches itself.

**Failure injection:** each endpoint accepts an optional `force_failure`
query param in test/staging configurations, used by integration tests to
deterministically exercise `execute`'s failure-routing path
(`execute -(failure)-> diagnose`) without depending on a real outage
occurring at test time.

**Gateway scope:** calls to `mock-staging-api` are plain `httpx` HTTP calls,
not LLM/embedding calls, and are therefore outside ADR-003's gateway
contract by design — the same precedent already established for the local
reranker (ADR-011) and, later, the fine-tuned embedding model (ADR-020).
