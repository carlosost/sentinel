# Feature 08 — `guardrail_output` Node

**Phase introduced:** Phase 4
**Status:** Done
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

## Implementation Status

### Implemented

- `src/graph/nodes/guardrail_output.py` (new): real `guardrail_output` node +
  `guardrail_output_route` path function, replacing
  `_guardrail_output_placeholder`. One function pair serves both call sites
  per ADR-014, distinguishing pre-/post-execution by checking
  `state["execution_result"]` rather than by graph position. Routes:
  unsafe -> `reject`; safe + `execution_result` set -> `end` (post-execution);
  safe + `execution_result` unset -> `await_human_approval` if
  `proposed_action.side_effecting` else `execute` (pre-execution).
- **Implementation decision (not pinned by ADR-014's text, decided here):**
  what text gets moderated differs by call site, since no single field works
  for both. Pre-execution renders `diagnosis` + `proposed_action`;
  post-execution uses `postmortem_draft` once it exists (roadmap item 11).
  Documented in the module docstring.
- `src/graph/build.py`: `guardrail_output` is now the real node (was
  `_guardrail_output_placeholder`); added `_await_human_approval_placeholder`
  and `_execute_placeholder` (roadmap items 9–10) so the new conditional
  edges out of `guardrail_output` have somewhere to route to; both new
  placeholders edge straight to `END`.
- `src/graph/nodes/reject.py`: docstring updated to drop the "once Feature 08
  retrofits it" future tense (it's the present now).
- **Bug found and fixed during this feature**: `reject`'s original logic
  (`state.get("guardrail_input_verdict") or state.get("guardrail_output_verdict")`)
  picked `guardrail_input_verdict` whenever it was set — including when it
  was *safe* and a *later* `guardrail_output_verdict` was the one that was
  actually unsafe. Since `guardrail_input` always sets its verdict before
  `guardrail_output` ever runs, every run that reaches an unsafe output
  verdict has a safe input verdict already sitting in state, so the old logic
  reported the wrong (safe) verdict's `reason` ("stub" instead of the real
  rejection reason) on every output-side rejection. Fixed to check each
  verdict's own `verdict` field for `"unsafe"` rather than truthiness.
  Caught by this feature's new full-graph integration test
  (`test_graph_runs_full_path_unsafe_output_verdict_routes_to_reject`), not by
  any pre-existing test — Feature 03 never had a case where both verdicts
  could be set. A regression test was added directly to
  `tests/graph/nodes/test_reject.py`
  (`test_reject_node_uses_output_reason_when_input_was_safe`).

### Deviations from the PyTest skeletons

- Added tests beyond the skeletons: two tests asserting *what text* gets
  moderated at each call site (diagnosis/proposed_action pre-execution,
  postmortem_draft post-execution) — the skeleton only covered routing, not
  the rendering decision this feature also had to make.
- `tests/graph/test_skeleton.py`: extended both existing full-graph
  integration tests with `guardrail_output_verdict`/`rejection_reason`
  assertions, and added two new full-graph integration tests:
  `test_graph_runs_full_path_unsafe_output_verdict_routes_to_reject` (proves
  the bug above is actually fixed end-to-end, not just unit-tested) and
  `test_graph_runs_full_path_side_effecting_action_reaches_await_human_approval`
  (proves the safe + side-effecting branch reaches the new placeholder).

### Verification

- `python3 -m unittest discover -s tests` → **111/111 passing** (up from 101;
  +9 in `test_guardrail_output.py`, +1 regression case in `test_reject.py`).
- `bash scripts/lint_gateway_usage.sh` → passed.
- `python3 scripts/run_eval.py` → passed (harness mechanics only).

### Definition of Done

- [x] ADR-014 (pre-drafted in docs/PROJECT_MEMORY.md) re-verified against the
      actual Feature 03-07 codebase and confirmed accurate — implemented as
      specified.
- [x] `guardrail_output` node + routing function implemented, reused at the
      one currently-reachable call site (pre-execution); designed to also
      serve the post-execution call site once `write_postmortem` exists.
- [x] `_await_human_approval_placeholder`/`_execute_placeholder` added so the
      new routes have valid targets.
- [x] `reject`'s pre-existing verdict-selection bug found and fixed, with a
      regression test.
- [x] All Gherkin scenarios covered by passing tests, plus additional edge
      cases.
- [x] Full test suite, lint, and eval harness all pass.
- [x] `docs/PROJECT_MEMORY.md` updated (Feature Log, §9 item 8; Open Question #6
      marked Resolved by ADR-014).
