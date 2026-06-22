# Feature 09 — `await_human_approval` Interrupt Node + `PostgresSaver` Wiring

**Phase introduced:** Phase 4
**Status:** In Progress (design complete; implementation/tests pending)
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
