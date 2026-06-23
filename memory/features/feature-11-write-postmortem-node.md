# Feature 11 — `write_postmortem` Node

**Phase introduced:** Phase 4
**Status:** Done
**PMA sections touched:** ADR-017 (new), §3 Pillar 3, §7 (new Open Question), §6
Feature Log, §9 item 11

## Feature Description

Add the `write_postmortem` node that drafts a postmortem from the diagnosis, action,
and execution result, then passes it through `guardrail_output` before `END`.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001, ADR-002 | No conflict — sequential node, no interrupt. |
| ADR-003 (Gateway) | No conflict, requirement carries forward: `write_postmortem`'s drafting call goes through `client_factory.get_chat_client(...)`. |
| ADR-004 through ADR-013 | No conflict — unrelated surfaces or already-established patterns (`execution_result` per ADR-016, `proposed_action`/`side_effecting` per ADR-013, `diagnosis_confidence` per ADR-013). |
| ADR-014 (`guardrail_output` retrofit) | No conflict — `write_postmortem -> guardrail_output` is exactly the post-execution call site ADR-014 already designed; this feature is what finally makes that path exercisable end-to-end with a real `postmortem_draft`. |
| ADR-015, ADR-016 | No conflict — `write_postmortem` reads `human_decision.note` and `execution_result` (ADR-016's shape) as narrative inputs without modifying either contract. |
| §5.1 IncidentState schema | No conflict — `postmortem_draft: Optional[str]` already exists as a plain string; no shape to pin beyond the field itself. |
| §5.2 Graph skeleton | No conflict — `execute -(success)-> write_postmortem -> guardrail_output` already exists exactly as needed. Fourth consecutive node feature (with 09, 10) requiring no skeleton correction; only the two guardrail features (03, 08) needed retrofits. |
| §5.3 Gateway contract | No conflict, same note as ADR-003. |

**Verdict: ADDITIVE.** No existing ADR or contract is contradicted.

## New ADR

### ADR-017: `write_postmortem` content sources and draft structure
- **Context:** `postmortem_draft` existed as a bare string field with no specification
  of what it should contain or how it should reflect upstream signals like
  `diagnosis_confidence`.
- **Decision:**
  - `write_postmortem` makes one LLM call through `client_factory.get_chat_client(...)`,
    drafting a postmortem with four fixed sections: **Summary**, **Root Cause**,
    **Action Taken & Outcome**, **Notes**.
  - Inputs: `diagnosis`, `proposed_action` (or `human_decision.modified_action` if
    present), `execution_result`, and `human_decision.note` if the run was approved
    with caveats.
  - **Confidence-aware narrative:** if `diagnosis_confidence == "low"`, the "Notes"
    section explicitly states the diagnosis was made under degraded retrieval
    confidence — this signal (already structured per ADR-013) is not silently
    dropped at the final reporting step.
  - The draft is then passed through `guardrail_output`'s post-execution call site
    (ADR-014) before `END`.
- **Consequences:** Establishes what "the postmortem" actually contains; changing the
  section structure later is a retrofit against this ADR.
- **Status:** Accepted.

## Blast Radius

Additive — no existing ADR superseded, no existing test/spec files broken.

**New Open Question flagged (not solved here):** there is no retry cap on
`execute -(failure)-> diagnose`, unlike the self-RAG loop's `retry_count < 2`
(ADR-012). A run that keeps failing execution could cycle indefinitely. Out of scope
for this feature (it's a `diagnose`/`execute` concern, not `write_postmortem`'s), but
flagged now since `write_postmortem` is the node that would otherwise never be
reached on such a run.

## Pillar Impact

- [x] 3. Guardrails — the post-execution `guardrail_output` branch (ADR-014) is now
      exercisable end-to-end for the first time, since a real `postmortem_draft`
      exists to moderate.
- [ ] 1, 2, 4, 5, 6 — not touched.

## Gherkin

```gherkin
Feature: write_postmortem drafts a structured postmortem

  Scenario: postmortem includes all four required sections
    Given state.diagnosis, state.proposed_action, and state.execution_result are set
    When the write_postmortem node runs
    Then state.postmortem_draft contains a Summary, Root Cause, Action Taken &
      Outcome, and Notes section

  Scenario: low-confidence diagnoses are flagged in the Notes section
    Given state.diagnosis_confidence is "low"
    When the write_postmortem node runs
    Then state.postmortem_draft's Notes section mentions degraded retrieval
      confidence

  Scenario: write_postmortem's LLM call goes through the gateway
    Given a mocked client_factory
    When the write_postmortem node runs
    Then client_factory.get_chat_client is called, not a direct provider SDK

  Scenario: the draft proceeds to guardrail_output's post-execution branch
    Given a drafted postmortem
    When the write_postmortem node completes
    Then the next edge target is "guardrail_output"
```

## PyTest Skeletons (all Deterministic Tier — section structure and routing, mocked LLM call; postmortem narrative quality is not asserted with `==` per §8.2)

```python
# tests/graph/nodes/test_write_postmortem.py

def test_postmortem_has_all_required_sections(mock_client_factory):
    """Deterministic Tier. Asserts section headers are present, not narrative
    quality."""
    ...

def test_low_confidence_diagnosis_is_flagged_in_notes(mock_client_factory):
    """Deterministic Tier. Enforces ADR-017's confidence-aware requirement
    structurally — checks for the flag's presence, not specific wording."""
    ...

def test_write_postmortem_uses_client_factory(mock_client_factory):
    """Deterministic Tier. Enforces ADR-003/006 on the drafting call."""
    ...

def test_write_postmortem_routes_to_guardrail_output():
    """Deterministic Tier."""
    ...
```

## Implementation Status

**What was built:**
- `src/graph/nodes/write_postmortem.py` (new): `write_postmortem(state)` — one LLM
  call via `client_factory.get_chat_client(model="sentinel-postmortem")`, JSON-parsed
  with `WritePostmortemError` on missing/invalid `postmortem_draft` (the established
  "never silently default" discipline). `_action_taken(state)` reuses
  `await_human_approval.resolve_action`'s ADR-015 precedence rule (`modified_action`
  over `proposed_action`), guarded by `human_decision is not None` the same way
  `execute._action_to_execute` is — not re-derived. Confidence-aware Notes append
  is a deterministic post-processing step (string append), not left solely to the
  model's own prose, so the structural contract in ADR-017 holds even if a
  completion's prose omits it. No `write_postmortem_route` function exists — the
  node always routes via a single static edge, matching the Gherkin's fourth
  scenario.
- `src/graph/build.py`: docstring's Feature 10 paragraph extended with Feature 11's
  paragraph; `_write_postmortem_placeholder` removed; `write_postmortem` imported
  and wired as the real node; the placeholder's `write_postmortem -> END` static
  edge replaced with the real `write_postmortem -> guardrail_output` edge (the
  post-execution call site ADR-014 designed and ADR-017 now makes reachable).
  Confirmed via a full re-read of `src/graph/_compat.py` that the shim's
  single-outgoing-edge constraint applies only to a node's *source* side — a node
  may be the *target* of multiple incoming edges from different sources, so
  `guardrail_output` now correctly has two incoming static edges
  (`propose_action -> guardrail_output` and `write_postmortem -> guardrail_output`)
  with no shim change required.
- `tests/graph/nodes/test_write_postmortem.py` (new) — 4 tests matching the spec's
  exact pre-drafted skeleton names.
- `tests/graph/test_skeleton.py` — both tests that previously stopped at
  `execute`/the placeholder (renamed
  `test_graph_runs_full_safe_path_high_relevance_reaches_execute_and_write_postmortem_placeholder`
  -> `..._reaches_execute_and_write_postmortem`) now add a
  `@patch("src.graph.nodes.write_postmortem.get_chat_client")` mock and assert
  `postmortem_draft` is set and the second (post-execution) `guardrail_output_verdict`
  reads "safe" before reaching `END`. Module docstring updated to describe the full
  `write_postmortem -> guardrail_output -> END` tail.
- `tests/graph/test_hitl_checkpoint_restart.py` — the restart test gets the same
  `write_postmortem.get_chat_client` patch and a `postmortem_draft is not None`
  assertion on the resumed state (the "second process" reaches `write_postmortem`
  too).

**Deviations from spec:** none structural. The Gherkin/PyTest skeletons didn't
specify exact mock-arg shapes; tests assert section-header substring presence
(`assertIn`) per §8.2's narrative-quality-is-Probabilistic-Tier discipline, never
`==` against full draft text.

**New Open Question added to PROJECT_MEMORY.md §7** (per this feature's own Blast
Radius note, not resolved here): no retry cap exists on `execute -(failure)->
diagnose`, unlike the self-RAG loop's bounded `retry_count < 2` (ADR-012).

**Verification:**
- `python -m unittest discover -s tests -p "test_*.py"`: 141/141 passing.
- `bash scripts/lint_gateway_usage.sh`: PASS.
- `python scripts/run_eval.py`: PASS (harness mechanics only, no quality baseline
  yet — unchanged caveat carried from Feature 02).

**Definition of Done:**
- [x] Conflict Check confirmed authoritative (no skeleton correction needed).
- [x] ADR-017 implemented as specified.
- [x] Gherkin scenarios covered by PyTest skeletons, names matching exactly.
- [x] `guardrail_output.py` confirmed to need zero changes.
- [x] `build.py` wired: real node, real edge, placeholder removed.
- [x] Full test suite green, lint green, eval harness green.
- [x] New Open Question flagged in PMA (not solved, not deleted-then-forgotten).
- [x] PROJECT_MEMORY.md Feature Log row, ADR-017 status, §3 Pillar 3, §9 checkbox
  updated.
