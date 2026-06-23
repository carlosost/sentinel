# Feature 09 — `await_human_approval` Interrupt Node + `PostgresSaver` Wiring

**Phase introduced:** Phase 4
**Status:** Done
**PMA sections touched:** ADR-015 (new), §5.1, §3 Pillar 2, §7 (new Open Question,
clarifies #9), §6 Feature Log, §9 item 9

## Feature Description

Add the `await_human_approval` interrupt node and wire `PostgresSaver` so any
`side_effecting=True` proposed action pauses the graph durably until a human submits
an `{approved, modified_action, note}` decision.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — durable interrupt/resume is the load-bearing reason LangGraph was chosen at all (§1). |
| ADR-002 (Postgres checkpointer) | No conflict — this feature is the first actual wiring of `PostgresSaver` into `src/graph/build.py`, directly implementing what ADR-002 specified. |
| ADR-003 (Gateway) | No conflict — no LLM call in this node; pure control flow plus human input. |
| ADR-004 (Guardrails) | No conflict — `await_human_approval` sits after `guardrail_output`'s safe+side_effecting branch (ADR-014), unaffected by this feature. |
| ADR-005 (Eval strategy) | No conflict — HITL was already marked "n/a (human judgment is out of scope for both tiers)" in §8.2's pillar mapping table; no new eval surface introduced. |
| ADR-006 (Lint) | No conflict. |
| ADR-007 (Scaffolding) | No conflict, real gap: no Active Contract exists yet for the HTTP API layer that would let a human actually submit a decision (start-run and submit-approval endpoints). Out of scope for this feature — deferred as a new Open Question rather than silently designed here. |
| ADR-008 (Eval harness) | No conflict. |
| ADR-009, ADR-010, ADR-011 | No conflict — unrelated surfaces. |
| ADR-012 (Self-RAG mechanics) | No conflict. |
| ADR-013 (`proposed_action`/`side_effecting`) | No conflict — `await_human_approval` is reached precisely because `guardrail_output` already classified the action as `side_effecting=True` (ADR-013/014). |
| ADR-014 (`guardrail_output` retrofit) | No conflict — this feature picks up exactly where ADR-014's safe+side_effecting branch leaves off. |
| §5.1 IncidentState schema | No conflict on existing keys — `human_decision: Optional[dict]` already exists with the `{approved, modified_action, note}` shape described in Pillar 2's prose. Gap: that shape was never formalized as a typed structure the way ADR-011/013 formalized other dicts; and nothing states whether `execute` (roadmap item 10) should prefer `human_decision.modified_action` over `proposed_action` when both are present. Both filled additively below. |
| §5.2 Graph skeleton | No conflict — `guardrail_output -(safe, side_effecting)-> await_human_approval`, `await_human_approval -(approved)-> execute`, and `await_human_approval -(rejected)-> diagnose` already exist exactly as needed. First node feature since Feature 05 that requires **no** skeleton correction. |
| §5.3 Gateway contract | No conflict — not applicable, no model call in this node. |

**Verdict: ADDITIVE.** No existing ADR or contract is contradicted; gaps filled are
the `HumanDecision` shape formalization and the `modified_action` precedence rule for
`execute`'s future implementation.

## New ADR

### ADR-015: HITL resume contract formalization; `PostgresSaver` wiring; `modified_action` precedence
- **Context:** Pillar 2's prose already specified the resume payload shape informally;
  this feature is the first to actually need it typed and to specify how a later node
  (`execute`, roadmap item 10) should reconcile a human's edit against the original
  proposal.
- **Decision:**
  - **`HumanDecision` shape** (formalizing `human_decision: Optional[dict]`):
    `{"approved": bool, "modified_action": Optional[dict], "note": str}`. No change to
    the field's existence — this only pins its internal shape, consistent with how
    ADR-011 and ADR-013 pinned other dict fields.
  - **`modified_action` precedence:** when `await_human_approval` resumes with
    `approved=True`, `execute` (roadmap item 10) must use
    `human_decision.modified_action` if it is not `None`, falling back to
    `proposed_action` otherwise. This is forward groundwork for item 10, the same
    pattern Feature 07 used for `side_effecting`.
  - **Checkpointer wiring:** `src/graph/build.py` compiles the graph with
    `PostgresSaver` pointed at the same Postgres instance used for pgvector (ADR-002).
    `await_human_approval` is implemented via LangGraph's `interrupt()`, which
    naturally halts execution and persists the checkpoint without any extra code in
    the node body beyond calling `interrupt(...)`.
  - **Test-schema Postgres:** integration tests for this node run against a real
    (test-schema) `PostgresSaver`, per the pattern already described in Workflow
    Blueprint §8.1's worked example (c) — kill and reinstantiate the graph object to
    simulate a process restart, then resume.
  - **Out of scope, deferred:** the HTTP API surface (endpoints to start a run and to
    submit an approval decision) is not designed here — tracked as a new Open
    Question. This feature only specifies the graph-level interrupt/resume mechanics,
    testable directly via `graph.invoke(...)`/`graph.invoke(Command(resume=...))`
    without an HTTP layer.
- **Consequences:** `execute` (item 10) has an unambiguous rule for which action to
  run; the HTTP layer, whenever built, has a typed payload to deserialize into.
- **Status:** Accepted.

## Blast Radius

Additive — no existing ADR superseded, no existing test/spec files broken.

**Note on Open Question #9 (diagnose re-entry):** this feature wires the
`await_human_approval -(rejected)-> diagnose` edge for the first time, but does
**not** change `diagnose`'s prompt/behavior to specifically use `human_decision.note`
as context on re-entry — the routing now exists and is testable, but the "how
`diagnose` should use the rejection context" question from Feature 07 remains open.
Not resolved, only partially de-risked.

## Pillar Impact

- [x] 2. Human-in-the-Loop — `interrupt()`, `PostgresSaver` wiring, and the
      `approved`/`rejected` resume routing are now fully specified for the first time.
      The restart-survival property (§1 success criterion) is testable per the §8.1(c)
      pattern.
- [ ] 1, 3, 4, 5, 6 — not touched.

## Gherkin

```gherkin
@hitl
Feature: await_human_approval pauses the graph durably for side-effecting actions

  Scenario: graph halts at await_human_approval and persists the checkpoint
    Given state.proposed_action.side_effecting is true
    And guardrail_output has just routed here with a safe verdict
    When the graph reaches await_human_approval
    Then execution halts before execute
    And the checkpoint is persisted under the run's thread_id

  Scenario: resuming an approved decision proceeds to execute
    Given a paused thread with human_decision = {"approved": true, "modified_action": null, "note": "looks good"}
    When the graph is resumed for that thread_id
    Then the next node to run is "execute"
    And execute uses proposed_action (modified_action was null)

  Scenario: resuming an approved decision with a human edit overrides the proposal
    Given a paused thread with human_decision = {"approved": true, "modified_action": {"tool": "rollback_deploy", "args": {"to_version": "v2.2.9"}}, "note": "use the older version"}
    When the graph is resumed for that thread_id
    Then the next node to run is "execute"
    And execute uses human_decision.modified_action, not proposed_action

  Scenario: resuming a rejected decision returns to diagnose
    Given a paused thread with human_decision = {"approved": false, "modified_action": null, "note": "wrong root cause"}
    When the graph is resumed for that thread_id
    Then the next node to run is "diagnose"

  Scenario: the paused run survives a simulated process restart
    Given a paused thread persisted via PostgresSaver
    When the graph object is destroyed and a new graph object is instantiated against the same Postgres instance
    And the graph is resumed for that thread_id with an approved decision
    Then the run resumes correctly at await_human_approval's successor, not from entry
```

## PyTest Skeletons (Deterministic Tier for routing logic; Integration Tier against a real test-schema Postgres for the interrupt/checkpoint/restart boundary, per §8.5 item 3 — both are still non-probabilistic, no model-output judgment involved)

```python
# tests/graph/nodes/test_await_human_approval.py

def test_approved_with_no_modification_routes_to_execute_with_proposed_action():
    """Deterministic Tier. Asserts routing and that execute receives proposed_action
    unchanged when modified_action is None."""
    ...

def test_approved_with_modification_routes_to_execute_with_modified_action():
    """Deterministic Tier. Asserts the ADR-015 precedence rule: modified_action wins
    when present."""
    ...

def test_rejected_routes_to_diagnose():
    """Deterministic Tier. Asserts routing only — does not assert how diagnose uses
    the rejection note (Open Question #9 remains open)."""
    ...


# tests/graph/test_hitl_checkpoint_restart.py

def test_run_pauses_at_await_human_approval_and_persists_checkpoint(test_postgres_saver):
    """Integration Tier (real test-schema Postgres, per §8.1 worked example c).
    Deterministic in nature — asserts control-flow/persistence facts, not model
    judgment."""
    ...

def test_resume_after_simulated_process_restart_continues_correctly(test_postgres_saver):
    """Integration Tier. Kills and reinstantiates the graph object against the same
    Postgres instance, then resumes — the core HITL durability guarantee from §1's
    success criteria."""
    ...
```

## Implementation Status

**Status: Done.**

### What was built

- **`src/graph/_compat.py` addendum** — added `GraphInterrupt` (exception),
  `interrupt(value)` (always raises `GraphInterrupt(value)` — see deviation
  below), and checkpointer support: `StateGraph.compile(checkpointer=None)`,
  `_CompiledGraph.invoke(input_, *, config=None, max_steps=...)` (now accepts
  `config={"configurable": {"thread_id": ...}}` and `input_=None` to resume),
  and a new `_CompiledGraph.update_state(config, values)` method that merges
  values into a paused thread's persisted state without resuming — the
  write-then-resume two-step the PMA's own Pillar 2 prose already specified
  (`update_state(...)` then `invoke(None, config=...)`).
- **`src/graph/checkpoint.py` (new)** — `InMemoryCheckpointSaver`, the
  sandbox stand-in for `PostgresSaver` (ADR-021 addendum). Stores
  `(state, paused_node)` per `thread_id`, deep-copying on both save and load
  so neither side can mutate the other's view. `CheckpointNotFoundError` on
  `load()` of an unknown `thread_id` — never fabricates an empty state.
- **`src/graph/nodes/await_human_approval.py` (new)** — `await_human_approval`
  (interrupts when `human_decision` is unset, no-ops once it's set),
  `await_human_approval_route` (routes `approved`/`rejected`), and
  `resolve_action` (ADR-015's `modified_action`-over-`proposed_action`
  precedence rule, forward groundwork for `execute`/Feature 10).
- **`src/graph/state.py`** — added the `HumanDecision` TypedDict
  (`{approved, modified_action, note}`) and retyped `human_decision` to
  `Optional[HumanDecision]`.
- **`src/graph/build.py`** — `build_graph(checkpointer=None)` now takes an
  optional checkpointer (omitted preserves every pre-Feature-09 caller's
  behavior exactly); `_await_human_approval_placeholder` removed, real
  `await_human_approval` node wired with conditional edges
  `-(approved)-> execute`, `-(rejected)-> diagnose`. `_execute_placeholder`
  unchanged (Feature 10).
- **Tests**: `tests/graph/test_compat.py` (+5 cases for the addendum),
  `tests/graph/test_checkpoint.py` (new, 6 cases), `tests/graph/nodes/
  test_await_human_approval.py` (new, matches the 3 pre-drafted skeleton
  names exactly), `tests/graph/test_hitl_checkpoint_restart.py` (new, matches
  the 2 pre-drafted skeleton names, models "destroy and reinstantiate the
  graph object" via `del` + a second `build_graph()` call sharing one
  checkpointer instance). `tests/graph/test_skeleton.py`'s side-effecting test
  rewritten to do a full interrupt -> `update_state` -> resume round trip
  instead of asserting a placeholder no-op.

### Deviations from the spec (and why)

1. **`interrupt()` always raises — it never returns a value, even
   conceptually, on resume.** Real langgraph's `interrupt()` suspends a
   generator and, on resume, *returns* the value passed to `Command(resume=
   ...)`. This stdlib shim has no generator/coroutine machinery to replay a
   function mid-execution, so faithfully reproducing that return-value
   semantics isn't possible without a much larger rewrite of `_compat.py`
   than this feature's scope warrants. Instead, `await_human_approval` is
   written to be safely re-run on resume: it checks `state.get("human_decision")`
   itself and only calls `interrupt()` when it's still unset. This is
   documented at length in `_compat.py`'s ADDENDUM docstring and the node's
   own docstring, flagged as a deliberate, known shim limitation (extending
   Open Question #15), not a silent gap.
2. **Resume mechanism is `update_state(config, values)` then
   `invoke(None, config=...)`**, not `Command(resume=...)` — this follows the
   PMA's own pre-existing Pillar 2 prose (`graph.invoke(None,
   config={"configurable": {"thread_id": ...}})`) read verbatim before any
   code was written for this feature, rather than the Gherkin's looser
   "the graph is resumed for that thread_id" phrasing, which didn't pin a
   specific API. `update_state` is new (not previously specified) but is the
   natural complement needed to make the PMA's own resume convention work.
3. **Test-schema Postgres → `InMemoryCheckpointSaver`.** Per ADR-021 (no
   PyPI egress, no live Postgres in this sandbox), both new test files use
   the in-memory checkpointer shim instead of a real `test_postgres_saver`
   fixture. The "destroy and reinstantiate the graph object" restart
   simulation is preserved exactly — only the backing store differs. Test
   names match the spec's skeletons exactly (`test_run_pauses_at_
   await_human_approval_and_persists_checkpoint`,
   `test_resume_after_simulated_process_restart_continues_correctly`) so a
   future swap to real Postgres only needs to change the fixture, not the
   test names/structure.
4. **`diagnose` re-entry**: per the spec's own Blast Radius note, the
   `await_human_approval -(rejected)-> diagnose` edge is wired and tested
   (`test_rejected_routes_to_diagnose`), but `diagnose`'s prompt/behavior is
   untouched — it does not yet use `human_decision.note` as context. Open
   Question #9 remains open, only partially de-risked, exactly as the spec
   anticipated.

### Verification

- `python -m unittest discover -s tests -p "test_*.py"`: **129/129 passing**
  (was 111 after Feature 08; +18 from this feature's new/extended test files).
- `bash scripts/lint_gateway_usage.sh`: PASS (no direct provider imports).
- `python scripts/run_eval.py`: harness mechanics PASS (no new gap introduced
  — `await_human_approval` makes no model call).

### Definition of Done

- [x] Spec read and Conflict Check verified (no skeleton correction needed,
      confirmed).
- [x] `HumanDecision` shape formalized in `state.py`.
- [x] `modified_action` precedence rule implemented as `resolve_action`,
      forward groundwork for Feature 10.
- [x] Checkpointer wiring added to `build_graph()`, off by default.
- [x] `await_human_approval` interrupts and persists; resumes correctly via
      `update_state` + `invoke(None, ...)`.
- [x] Restart-survival property tested (two separate graph objects, one
      checkpointer instance).
- [x] All Gherkin scenarios covered by tests (approved/no-modification,
      approved/modification, rejected, pause+persist, restart+resume).
- [x] HTTP API layer explicitly deferred — new Open Question recorded in PMA.
- [x] PMA updated (Feature Log, ADR-015 status, §9 checkbox).
