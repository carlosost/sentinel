# Feature 10 — `execute` Node

**Phase introduced:** Phase 4
**Status:** In Progress (design complete; implementation/tests pending)
**PMA sections touched:** ADR-016 (new), §5.1, §3 Pillar 2, §7 (resolves Open
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
