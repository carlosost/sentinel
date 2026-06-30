# Feature 03 — `guardrail_input` Node

**Phase introduced:** Phase 4
**Status:** Done — implemented and tested (against sandbox shims; see Implementation Status below).
**PMA sections touched:** ADR-009, ADR-021 (addendum), §5.1 (new field), §5.2 (corrected),
§3 Pillar 3, §6 Feature Log, §9 item 3

## Feature Description

Add the `guardrail_input` node: on graph entry, call `guardrail_check()` on the raw
alert text and route to a `reject` node on an unsafe verdict, router otherwise.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — adding the first real node to the `StateGraph`, as designed. |
| ADR-002 (Postgres checkpointer) | No conflict — no interrupt on this path. |
| ADR-003 (Gateway for every model call) | No conflict — `guardrail_input` calls `guardrail_check()`, which currently makes no LLM call at all (stub, per ADR-007); when it becomes real (roadmap item 13), it will go through the gateway per ADR-008's precedent. |
| ADR-004 (Guardrail stub wired from commit 1) | No conflict — this is the wiring ADR-004 promised: the call site now actually exists on a real node, not just the bare function. |
| ADR-005 (Eval strategy) | No conflict — unrelated. |
| ADR-006 (Lint enforcement) | No conflict — no new model-client construction here. |
| ADR-007 (Repo scaffolding) | No conflict, minor gap: ADR-007 named `src/graph/build.py` but not a location for individual node functions. Resolved additively in ADR-009 below (`src/graph/nodes/`) rather than treated as a contradiction. |
| ADR-008 (Eval harness) | No conflict — unrelated. |
| §5.1 IncidentState schema | **No conflict on existing fields**, but the `reject` node (required by this feature's own description) needs somewhere to record *why* a run was rejected, and no such field exists. Addressed as an additive field in ADR-009, not a redefinition of any existing key. |
| §5.2 Graph skeleton | **Conflict.** The skeleton currently shows a single unconditional edge `guardrail_input -> router`, with no `reject` branch — but ADR-004, the Pillar 3 blueprint, and the Workflow Blueprint's own worked example (§8.1d) all already describe a guardrail node that routes to rejection on an unsafe verdict. The skeleton as written contradicts the rest of the PMA. This is a documentation gap in §5.2, not a deliberate decision to route everything through `router` unconditionally — corrected below in ADR-009. |
| §5.3 Gateway contract | No conflict. |

**Verdict: RETROFIT** (narrowly — only §5.2's omission of the rejection branch, plus one additive field in §5.1). No prior ADR is reversed; §5.2 is corrected to match what every other section already assumed.

## New ADR (Retrofit)

### ADR-009: Correct graph skeleton to include guardrail rejection branches; add `rejection_reason` field
- **Context:** §5.2's original skeleton wrote `guardrail_input -> router` as a single
  unconditional edge, omitting the rejection branch that ADR-004, the Pillar 3
  blueprint, and Workflow Blueprint §8.1(d) all already assumed exists. Implementing
  `guardrail_input` faithfully to those sections required noticing and fixing this gap
  rather than silently picking one interpretation.
- **Decision:**
  - §5.2 is corrected: `guardrail_input` has a conditional edge —
    `guardrail_input -(verdict=unsafe)-> reject` and
    `guardrail_input -(verdict=safe)-> router`.
  - A new terminal `reject` node is added: it writes `state.rejection_reason` from the
    guardrail verdict and routes to `END`.
  - `IncidentState` (§5.1) gains one additive field: `rejection_reason: Optional[str]`.
    No existing field is renamed or retyped.
  - Node implementations live in `src/graph/nodes/` (one module per node), extending
    ADR-007's scaffolding, which named `build.py` for graph assembly but not a home
    for node logic.
  - **Flagged, not yet fixed:** `guardrail_output` (§5.2) has the same single-edge gap
    relative to Pillar 3's description of exit-side rejection. It is intentionally
    *not* corrected here, to keep this retrofit's blast radius scoped to
    `guardrail_input` — tracked as a new Open Question (see below) to be retrofitted
    formally when roadmap item 8 (`guardrail_output` node) is built.
- **Consequences:** §5.2 now accurately reflects the rejection-branch behavior every
  other section already described; no behavior actually changes for any node already
  built (only `guardrail_input` exists so far).
- **Status:** Accepted.

## Blast Radius

- **§5.2 corrected** (not superseding any numbered ADR — no ADR previously asserted
  the single-edge version; it was a contract drafting gap, now fixed).
- **§5.1 gains an additive field** (`rejection_reason`) — non-breaking, no existing
  consumer reads or writes this key today.
- **Feature 01's `test_empty_graph_invoke_returns_unchanged_state` is naturally
  retired**, not retrofitted: that test asserted the *placeholder* entry→END graph
  before any real node existed. Adding `guardrail_input` is expected evolution of that
  skeleton, not a violated contract — the test's job was to validate the skeleton
  mechanism prior to node logic, and it has done that job. It should be deleted or
  replaced with `test_graph_runs_guardrail_input_then_router_on_safe_verdict`, not kept
  alongside the new node.
- **New Open Question added:** `guardrail_output` has the same single-edge gap and will
  need the identical retrofit treatment when roadmap item 8 lands — recorded in §7 so
  it isn't forgotten.

## Pillar Impact

- [x] 3. Guardrails — first real call site for `guardrail_check()`; trigger-routing
      logic (safe → router, unsafe → reject) implemented and testable, still against
      the stub verdict.
- [ ] 1, 2, 4, 5, 6 — not touched.

## Gherkin

```gherkin
@guardrail
Feature: guardrail_input gates entry into the graph

  Scenario: safe input routes to router
    Given guardrail_check is mocked to return verdict "safe" for direction "input"
    And a minimal IncidentState with raw_alert set
    When the guardrail_input node runs
    Then state.guardrail_input_verdict.verdict equals "safe"
    And the next edge target is "router"

  Scenario: unsafe input routes to reject
    Given guardrail_check is mocked to return verdict "unsafe" for direction "input"
    And a minimal IncidentState with raw_alert set
    When the guardrail_input node runs
    Then state.guardrail_input_verdict.verdict equals "unsafe"
    And the next edge target is "reject"

@guardrail
Feature: reject node terminates the run with a recorded reason

  Scenario: reject node records the rejection reason and ends
    Given a state with guardrail_input_verdict.verdict "unsafe" and reason "stub-unsafe-example"
    When the reject node runs
    Then state.rejection_reason equals "stub-unsafe-example"
    And the next edge target is END
```

## PyTest Skeletons (all Deterministic Tier — trigger-routing contract, mocked guardrail_check)

```python
# tests/graph/nodes/test_guardrail_input.py

def test_guardrail_input_routes_to_router_on_safe_verdict(mock_guardrail_check):
    """Deterministic Tier. guardrail_check mocked to return 'safe'; asserts state
    field populated and routing target is 'router'. Never asserts moderation
    accuracy."""
    ...

def test_guardrail_input_routes_to_reject_on_unsafe_verdict(mock_guardrail_check):
    """Deterministic Tier. guardrail_check mocked to return 'unsafe'; asserts routing
    target is 'reject'."""
    ...


# tests/graph/nodes/test_reject.py

def test_reject_node_records_reason_and_routes_to_end():
    """Deterministic Tier. Pure state-transition test, no model calls involved."""
    ...


# tests/graph/test_skeleton.py  (superseding the Feature 01 placeholder test)

def test_graph_runs_guardrail_input_then_router_on_safe_verdict(mock_guardrail_check):
    """Deterministic Tier. Integration-style test of the real entry path, replacing
    Feature 01's entry->END smoke test now that a real node exists."""
    ...
```

## Implementation Status (real code/tests, sandbox-constrained)

Implemented:
- `src/graph/nodes/guardrail_input.py` — `guardrail_input(state)` calls
  `guardrail_check(raw_alert, direction="input")` and records the verdict;
  `guardrail_input_route(state)` is the separate path function (returns
  `"safe"`/`"unsafe"`, exported as `ROUTE_SAFE`/`ROUTE_UNSAFE`) passed to
  `add_conditional_edges` in `build.py` — node logic and routing logic are split,
  matching real LangGraph's own node/path-function convention.
- `src/graph/nodes/reject.py` — `reject(state)` reads
  `guardrail_input_verdict`/`guardrail_output_verdict` (falls back to the latter
  for when Feature 08 wires its own rejection branch per Open Question #6) and
  records `rejection_reason`; routes to `END` via a static edge.
- `src/graph/state.py` — `rejection_reason: Optional[str]` added additively, per
  ADR-009.
- `src/graph/build.py` — rewritten: `guardrail_input` is now the real entry node
  (`START -> guardrail_input`), with `add_conditional_edges("guardrail_input",
  guardrail_input_route, {"safe": "router", "unsafe": "reject"})`. `router` is a
  placeholder (`_router_placeholder`, routes straight to `END`) until Feature 04 —
  the same "placeholder until the next feature lands" pattern Feature 01 used for
  `_entry`.
- **`src/graph/_compat.py` extended (ADR-021 addendum, not a new ADR):** this
  feature is the first to need real branching, which the shim explicitly didn't
  support before now. Added `StateGraph.add_conditional_edges(source, path,
  path_map)` — a separate API from `add_edge`, mirroring real langgraph's actual
  branching model (real langgraph doesn't do multi-target `add_edge` either).
  `compile()` now does a static DFS from `START` across every conditional branch
  (not just one path) to detect cycles ahead of time; `add_edge` still rejects a
  second outgoing edge from the same source, and a node can't mix one static edge
  with one conditional-edges call. Cycles remain unsupported — still blocking for
  Feature 06.
- Tests: `tests/graph/nodes/test_guardrail_input.py`,
  `tests/graph/nodes/test_reject.py`, `tests/graph/test_skeleton.py` (new); 6 new
  cases added to `tests/graph/test_compat.py` covering
  `add_conditional_edges` (correct branch routing, direct-to-`END` targets,
  compile-time cycle detection through a conditional branch, runtime error on an
  unknown path-function return value, and the static/conditional mutual-exclusion
  rule).

Deviations from the original skeleton:
- `tests/graph/test_build.py`'s Feature 01 placeholder test
  (`test_empty_graph_passes_through_to_end`) was deleted, not retrofitted, per
  this feature's own Blast Radius note — `tests/graph/test_skeleton.py` replaces
  it with two cases (safe-routes-through, unsafe-routes-to-reject) instead of the
  skeleton's single named case, since both branches needed direct coverage.
  `test_build.py` now only asserts the graph compiles.
- The node-level `guardrail_input` tests assert `guardrail_input_route(state)`
  returns the path-function key (`"safe"`/`"unsafe"`), not the final node name
  (`"router"`/`"reject"`) — that translation is `build.py`'s `path_map`, not the
  node module's concern. The Gherkin's "next edge target is 'router'" is verified
  end-to-end instead, in `test_skeleton.py`.
- All tests are `unittest`, not `pytest`, continuing Feature 01's ADR-021
  fallback.

Verification performed in-sandbox: `bash scripts/lint_gateway_usage.sh` passes;
`python3 -m unittest discover -s tests -v` → 39/39 passing (28 carried over from
Features 01-02 + 11 new); `bash scripts/entrypoint.sh smoke` still passes (the
smoke check's hardcoded state dict has no `rejection_reason` key, which is fine —
`reject()` and the smoke path don't require it, and `IncidentState` is a
`TypedDict`, not runtime-enforced).

Definition of Done — checked against §8.5:
- [x] Spec (this file) exists and was conflict-checked against prior ADRs.
- [x] Gherkin scenarios map 1:1 to implemented unittest cases.
- [x] Tests pass deterministically, no live network/API keys required.
- [x] docs/PROJECT_MEMORY.md and this file updated in the same pass as the code.
- [ ] Real-package parity (Open Question #15, now also covering `_compat.py`'s
      `add_conditional_edges`) — not yet verified against real `langgraph`.
