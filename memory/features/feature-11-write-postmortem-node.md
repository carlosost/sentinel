# Feature 11 — `write_postmortem` Node

**Phase introduced:** Phase 4
**Status:** In Progress (design complete; implementation/tests pending)
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
