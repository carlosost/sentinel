# Feature 08 — `guardrail_output` Node

**Phase introduced:** Phase 4
**Status:** In Progress (design complete; implementation/tests pending)
**PMA sections touched:** ADR-014 (new, retrofit), §5.2, §3 Pillar 3, §7 (resolves
Open Question #6), §6 Feature Log, §9 item 8

## Feature Description

Add the `guardrail_output` node: run `guardrail_check()` on the proposed remediation
explanation and route to `reject` on an unsafe verdict. This is the retrofit that
Open Question #6 (added by Feature 03 / ADR-009) flagged but deliberately deferred.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — `guardrail_output` is reused at two existing graph positions, both already named in the skeleton. |
| ADR-002 (Postgres checkpointer) | No conflict — no interrupt in this node itself. |
| ADR-003 (Gateway) | No conflict — `guardrail_check()` is still the stub from ADR-007; no LLM call exists yet to route through the gateway. |
| ADR-004 (Guardrail stub wired from commit 1) | No conflict — this is exactly the exit-node wiring ADR-004 promised, completing what `guardrail_input` (Feature 03) started on the entry side. |
| ADR-005/006/007/008 | No conflict — node file `src/graph/nodes/guardrail_output.py`, no eval/lint implications beyond existing patterns. |
| ADR-009 (Skeleton retrofit — guardrail_input rejection branch) | No conflict — ADR-009 explicitly deferred this exact gap (`guardrail_output`'s missing rejection branch) to this feature; this is fulfilling that deferral, not contradicting it. |
| ADR-010, ADR-011, ADR-012, ADR-013 | No conflict — unrelated surfaces. |
| §5.1 IncidentState schema | No conflict — `guardrail_output_verdict` and `rejection_reason` already exist (from ADR-004's original schema and ADR-009 respectively); no new field needed. |
| §5.2 Graph skeleton | **Conflict — the exact gap ADR-009/Open Question #6 predicted.** `guardrail_output` currently has only `-(side_effecting action)-> await_human_approval` and `-(read-only action)-> execute` from the `propose_action` call site, and an unconditional `-> END` from the `write_postmortem` call site — no branch exists for an unsafe verdict at either call site. Corrected below. |
| §5.3 Gateway contract | No conflict. |

**Verdict: RETROFIT** (the deferred one — completes the correction ADR-009 already
announced was coming).

## New ADR (Retrofit)

### ADR-014: Wire `guardrail_output`'s rejection branches at both call sites
- **Context:** `guardrail_output` is called twice in the skeleton — after
  `propose_action` (pre-execution: the proposed remediation explanation) and after
  `write_postmortem` (post-execution: the postmortem draft). Neither call site had an
  unsafe-verdict branch; ADR-009 flagged this and deferred it to this feature
  (Open Question #6).
- **Decision:**
  - **Pre-execution call site** (`propose_action -> guardrail_output`):
    - `unsafe` -> `reject` (reusing Feature 03's `reject` node — nothing has executed
      yet, so a full rejection is safe and semantically correct).
    - `safe` + `proposed_action.side_effecting == true` -> `await_human_approval`.
    - `safe` + `proposed_action.side_effecting == false` -> `execute`.
  - **Post-execution call site** (`write_postmortem -> guardrail_output -> END`):
    - `unsafe` -> `reject`. Note the semantic difference from the pre-execution case:
      the remediation has already run; "reject" here means the postmortem draft is
      not surfaced and `rejection_reason` is recorded, **not** that the action is
      undone. `execution_result` remains in state regardless, preserved for audit.
    - `safe` -> `END` (unchanged).
  - Both call sites use the same node function (`guardrail_output` writes
    `guardrail_output_verdict` and is call-site-agnostic); the routing distinction is
    expressed in each call site's own conditional-edge function, which already has
    access to whether `execution_result` is set to tell the two positions apart.
- **Consequences:** §5.2 now has an explicit unsafe path from every guardrail node,
  closing the gap ADR-009 opened. Resolves Open Question #6.
- **Status:** Accepted.

## Blast Radius

- **§5.2 corrected** at both `guardrail_output` call sites — anticipated by ADR-009,
  not a surprise; no ADR is superseded (none previously asserted the missing branch
  as deliberate).
- **No existing test/spec file breaks** — `guardrail_output` was not implemented
  before this feature.
- **Open Question #6 resolved** — marked `Resolved by ADR-014` in §7, not deleted.

## Pillar Impact

- [x] 3. Guardrails — both graph exit/mid points now have real verdict-to-route
      wiring, completing the pattern `guardrail_input` (Feature 03) started. Still
      against the stub verdict — moderation accuracy remains roadmap item 13.
- [ ] 1, 2, 4, 5, 6 — not touched.

## Gherkin

```gherkin
@guardrail
Feature: guardrail_output gates the pre-execution remediation explanation

  Scenario: unsafe verdict routes to reject before execution
    Given guardrail_check is mocked to return verdict "unsafe" for direction "output"
    And state.proposed_action is set, state.execution_result is unset
    When the guardrail_output node runs
    Then the next edge target is "reject"

  Scenario: safe verdict with a side-effecting action routes to await_human_approval
    Given guardrail_check is mocked to return verdict "safe" for direction "output"
    And state.proposed_action.side_effecting is true
    When the guardrail_output node runs
    Then the next edge target is "await_human_approval"

  Scenario: safe verdict with a read-only action routes to execute
    Given guardrail_check is mocked to return verdict "safe" for direction "output"
    And state.proposed_action.side_effecting is false
    When the guardrail_output node runs
    Then the next edge target is "execute"

@guardrail
Feature: guardrail_output gates the post-execution postmortem draft

  Scenario: unsafe verdict on the postmortem routes to reject without undoing execution
    Given guardrail_check is mocked to return verdict "unsafe" for direction "output"
    And state.execution_result is set (action already executed)
    When the guardrail_output node runs
    Then the next edge target is "reject"
    And state.execution_result remains unchanged in state

  Scenario: safe verdict on the postmortem routes to END
    Given guardrail_check is mocked to return verdict "safe" for direction "output"
    And state.execution_result is set
    When the guardrail_output node runs
    Then the next edge target is END
```

## PyTest Skeletons (all Deterministic Tier — trigger-routing contract, mocked guardrail_check; moderation accuracy is out of scope until roadmap item 13)

```python
# tests/graph/nodes/test_guardrail_output.py

def test_unsafe_pre_execution_routes_to_reject(mock_guardrail_check):
    """Deterministic Tier."""
    ...

def test_safe_side_effecting_routes_to_await_human_approval(mock_guardrail_check):
    """Deterministic Tier."""
    ...

def test_safe_read_only_routes_to_execute(mock_guardrail_check):
    """Deterministic Tier."""
    ...

def test_unsafe_post_execution_routes_to_reject_preserves_execution_result(mock_guardrail_check):
    """Deterministic Tier. Asserts routing AND that execution_result is not cleared —
    the action already happened and the graph must not pretend otherwise."""
    ...

def test_safe_post_execution_routes_to_end(mock_guardrail_check):
    """Deterministic Tier."""
    ...
```
