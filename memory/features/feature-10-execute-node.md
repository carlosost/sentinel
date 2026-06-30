# Feature 10 — `execute` Node

**Phase introduced:** Phase 4
**Status:** Done
**PMA sections touched:** ADR-016 (new), ADR-021 (addendum), §5.1, §3 Pillar 2, §7 (resolves Open
Question #3), §6 Feature Log, §9 item 10

## Feature Description

Add the `execute` node that runs the approved remediation against [mocked tool calls /
a staging API — resolve Open Question #3 first], routing failures back to `diagnose`
and successes to `write_postmortem`.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — `execute` follows the skeleton's existing position. |
| ADR-002 (Postgres checkpointer) | No conflict — no interrupt here; resume already happened in `await_human_approval` (Feature 09). |
| ADR-003 (Gateway) | No conflict — `execute` makes an HTTP call to a tool's backing service, not an LLM/embedding call. Explicitly out of ADR-003's scope by design, same precedent as the local reranker (ADR-011), called out here so it isn't later mistaken for a gateway bypass. |
| ADR-004, ADR-005, ADR-006 | No conflict — unrelated surfaces. |
| ADR-007 (Scaffolding) | No conflict, gap: no location existed yet for tool-execution code or a mock backing service. Filled additively below. |
| ADR-008 | No conflict. |
| ADR-009 through ADR-012 | No conflict — unrelated surfaces. |
| ADR-013 (`side_effecting`/tool registry) | No conflict — `execute` is the direct consumer of the registry ADR-013 introduced; dispatches by `tool` name. |
| ADR-014 (`guardrail_output` retrofit) | No conflict — `execute` is reached only via `guardrail_output`'s safe+read-only branch or `await_human_approval`'s approved branch, both already wired. |
| ADR-015 (HITL resume contract) | No conflict — `execute` is the direct fulfillment of the `modified_action` precedence rule ADR-015 specified ahead of time as groundwork. |
| §5.1 IncidentState schema | No conflict on the existing key — `execution_result: Optional[dict]` was declared but its shape never pinned. Filled additively below. |
| §5.2 Graph skeleton | No conflict — `execute -(failure)-> diagnose` and `execute -(success)-> write_postmortem` already exist exactly as needed. Third feature in a recent run (with Feature 09) requiring **no** skeleton correction. |
| §5.3 Gateway contract | No conflict, same note as ADR-003. |
| **Open Question #3 (tool execution sandboxing)** | Not a conflict, but the explicit thing this feature must resolve per its own description. Resolved below — this was an acknowledged gap with an already-stated leaning ("likely mocked... not real production infra"), not a reversal of any decision. |

**Verdict: ADDITIVE.** No existing ADR or contract is contradicted; this feature
resolves an acknowledged open question and fills two unpinned gaps
(`execution_result` shape, tool-execution backing service).

## New ADR

### ADR-016: Tool execution sandboxing — mock staging API, `execution_result` shape (resolves Open Question #3)
- **Context:** `execute`'s actual backing mechanism for `restart_service`,
  `rollback_deploy`, `page_secondary_oncall`, and `fetch_additional_logs` was
  unspecified. Without an explicit decision, the Gherkin/PyTest written for this
  feature would have silently encoded an assumption (real infra vs. mock) that nothing
  in the PMA actually authorized.
- **Decision:**
  - **v1 executes against a mock staging API**, never real production infrastructure.
    A lightweight stub HTTP service (`mock-staging-api`) is added to
    `infra/docker-compose.yml` (extending ADR-007's scaffolding), simulating each
    registered tool with deterministic canned responses.
  - **Tool executors** (`src/tools/executors.py`): one function per tool name in the
    registry (ADR-013), each making an `httpx` call to `mock-staging-api`. Dispatch is
    by `proposed_action["tool"]` (or `human_decision.modified_action["tool"]` per
    ADR-015's precedence rule).
  - **Failure injection:** `mock-staging-api` can be configured (via request
    args/headers in test fixtures) to return an error for specific test cases, so the
    `execute -(failure)-> diagnose` path is deterministically testable, not dependent
    on a real failure occurring.
  - **`execution_result` shape** (formalizing `execution_result: Optional[dict]`):
    `{"tool": str, "args": dict, "success": bool, "output": str, "error": Optional[str]}`.
  - **Gateway scope confirmed:** `execute`'s HTTP calls to `mock-staging-api` are
    explicitly outside ADR-003's gateway contract — same precedent as the local
    reranker (ADR-011) — because they are tool/service calls, not LLM/embedding
    client calls.
- **Consequences:** Resolves Open Question #3. `write_postmortem` (roadmap item 11)
  can rely on `execution_result`'s exact shape. Swapping the mock staging API for a
  real one later is itself a retrofit against this ADR, not a transparent
  configuration change — the sandboxing decision is architectural, not incidental.
- **Status:** Accepted.

## Blast Radius

Additive — no existing ADR superseded, no existing test/spec files broken. Resolves
Open Question #3 (marked `Resolved by ADR-016` in §7, not deleted).

## Pillar Impact

- [x] 2. Human-in-the-Loop — closes the loop: Project Charter success criterion 3
      ("zero remediation tool calls execute without passing through the HITL
      interrupt node") is now end-to-end verifiable for the first time, since a real
      `execute` node exists to assert against.
- [ ] 1, 3, 4, 5, 6 — not touched.

## Gherkin

```gherkin
Feature: execute runs the approved action and routes on outcome

  Scenario: successful execution routes to write_postmortem
    Given mock-staging-api is mocked to return success for tool "rollback_deploy"
    And state.human_decision = {"approved": true, "modified_action": null, "note": "ok"}
    When the execute node runs
    Then state.execution_result.success is true
    And the next edge target is "write_postmortem"

  Scenario: failed execution routes back to diagnose
    Given mock-staging-api is mocked to return an error for tool "rollback_deploy"
    And state.human_decision = {"approved": true, "modified_action": null, "note": "ok"}
    When the execute node runs
    Then state.execution_result.success is false
    And state.execution_result.error is non-empty
    And the next edge target is "diagnose"

  Scenario: a human's modified_action is executed instead of the original proposal
    Given state.proposed_action = {"tool": "rollback_deploy", "args": {"to_version": "v2.3.1"}, "side_effecting": true}
    And state.human_decision = {"approved": true, "modified_action": {"tool": "rollback_deploy", "args": {"to_version": "v2.2.9"}}, "note": "use older version"}
    When the execute node runs
    Then the executor is called with args {"to_version": "v2.2.9"}, not {"to_version": "v2.3.1"}

  Scenario: execute never calls the gateway
    Given a mocked client_factory
    When the execute node runs
    Then client_factory.get_chat_client and client_factory.get_embedding_client are
      never called
```

## PyTest Skeletons (all Deterministic Tier — execution outcome and routing mechanics, mocked mock-staging-api responses; whether the action was the "right" remediation is judged elsewhere by `sentinel_remediation_judge`, not here)

```python
# tests/graph/nodes/test_execute.py

def test_successful_execution_routes_to_write_postmortem(mock_staging_api):
    """Deterministic Tier. Asserts execution_result.success and routing only."""
    ...

def test_failed_execution_routes_to_diagnose(mock_staging_api):
    """Deterministic Tier. Uses failure injection per ADR-016, not a real outage."""
    ...

def test_modified_action_takes_precedence_over_proposed_action(mock_staging_api):
    """Deterministic Tier. Enforces ADR-015's precedence rule at the one node that
    actually consumes it."""
    ...

def test_execute_never_calls_gateway(mock_client_factory):
    """Deterministic Tier. Confirms the ADR-016/ADR-011 scope boundary — tool
    execution is not a gateway-mediated call."""
    ...
```

## Implementation Status

**Status: Done.**

### What was built
- `src/tools/executors.py` (new): `ExecutorError`, `_StagingApiClient`,
  `get_staging_api_client()` factory, `execute_tool(tool, args)`. Validates the
  tool against `src/tools/registry.py` before any call (unknown tool ->
  `ExecutorError`, never silently dispatched); normalizes both a mocked
  success/error response *and* a raised client exception into
  `execution_result`'s pinned shape
  (`{"tool", "args", "success", "output", "error"}`) — a client exception is
  treated as a normal failure-path outcome (routes to `diagnose`), not a
  graph-crashing error.
- `src/graph/nodes/execute.py` (new): `execute(state)`, `execute_route(state)`,
  `ROUTE_SUCCESS`/`ROUTE_FAILURE`. `_action_to_execute()` applies ADR-015's
  `modified_action` precedence via `await_human_approval.resolve_action()`
  when `human_decision` is set (the approved-after-HITL path), otherwise
  executes `proposed_action` unchanged (the safe+read-only path that never
  passes through `await_human_approval`).
- `src/graph/build.py`: `_execute_placeholder` replaced with the real
  `execute` node; added `_write_postmortem_placeholder` (roadmap item 11,
  Feature 11) so `execute`'s success edge has a real target to land on;
  wired `execute -(success)-> write_postmortem`, `execute -(failure)->
  diagnose` via `add_conditional_edges`.
- Tests: `tests/graph/nodes/test_execute.py` (new, 4 tests matching the
  spec's skeleton names exactly), `tests/tools/test_executors.py` (new, 4
  tests covering `execute_tool` in isolation: success normalization, error
  normalization, exception normalization, unknown-tool hard-fail). Updated
  `tests/graph/test_skeleton.py` (both tests that reach `execute` now mock
  `get_staging_api_client` and assert `execution_result`) and
  `tests/graph/test_hitl_checkpoint_restart.py`'s resume test (same).

### Deviations from spec (and why)
1. **Mock staging API is an in-process stdlib stand-in, not a real
   `httpx`-backed call to a `mock-staging-api` docker-compose service.**
   ADR-016's literal design requires `httpx` and a Docker daemon to run the
   stub service; this sandbox has no PyPI egress (confirmed again this
   feature) and no Docker daemon (standing ADR-021 constraint). Followed the
   exact precedent `client_factory.get_chat_client`/`get_embedding_client`
   set: a factory function (`get_staging_api_client()`) returning a dataclass
   whose `.call()` raises `NotImplementedError` for the real path, trivially
   monkeypatched in tests. Logged as a new ADR-021 addendum (see below) — not
   a silent substitution.
2. **`execute_tool` catches and normalizes client exceptions into
   `execution_result.success = False`**, rather than only normalizing
   pre-shaped error dicts as the Gherkin's literal phrasing
   ("mock-staging-api is mocked to return an error") suggests. This is a
   superset, not a contradiction: a real network failure must route to
   `diagnose` exactly like a mocked error response does, so the node's
   contract holds either way. Both forms are tested (`test_executors.py`'s
   `test_error_response_is_normalized_with_error_message` and
   `test_client_exception_is_normalized_into_failure_not_raised`).
3. **No actual `infra/docker-compose.yml` `mock-staging-api` service or
   failure-injection request headers were added** — there is nothing to run
   them against in this sandbox. ADR-016's "Decision" bullets describing
   that service remain the target design for whenever this runs somewhere
   with Docker access (tracked under Open Question #15, same as every other
   sandboxed dependency).

### Verification
- `python -m unittest discover -s tests -p "test_*.py"`: 137/137 passing.
- `bash scripts/lint_gateway_usage.sh`: PASS — `execute`/`executors.py` make
  no provider SDK or `client_factory` calls (confirmed by
  `test_execute_never_calls_gateway`, not just the lint's static check).
- `python scripts/run_eval.py`: harness mechanics PASS (unaffected by this
  feature).

### Definition of Done
- [x] `execute` node implemented, consuming `resolve_action()` per ADR-015.
- [x] `execution_result` shape pinned and produced exactly as ADR-016 specifies.
- [x] Routes `-(success)-> write_postmortem`, `-(failure)-> diagnose`.
- [x] Never calls the gateway (`get_chat_client`/`get_embedding_client`).
- [x] Unknown tool hard-fails (`ExecutorError`), never silently dispatched.
- [x] All 4 pre-drafted PyTest skeleton names implemented and passing.
- [x] Existing integration tests (`test_skeleton.py`,
      `test_hitl_checkpoint_restart.py`) updated to mock the new dependency
      and pass.
- [x] `docs/PROJECT_MEMORY.md` updated (Feature Log, ADR-016, ADR-021 addendum,
      §7 Open Question #3, §3 Pillar 2, §9 checkbox).
