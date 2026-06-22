# Feature 02 — Eval Harness

**Phase introduced:** Phase 4
**Status:** In Progress (design complete; implementation/tests pending; no baseline score recorded yet — see note below)
**PMA sections touched:** ADR-008 (new), §3 Pillar 4, §6 Feature Log, §9 item 2

## Feature Description

Build the eval harness: author `evals/golden_incidents.jsonl` (20+ synthetic incidents
with reference root cause, reference remediation, and pass/fail rubric), write
`evals/judge_prompt.md`, and wire ragas (`context_precision`, `context_recall`,
`faithfulness`) plus a LangSmith custom evaluator into CI.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — eval harness runs against traces/golden data, not graph control flow. |
| ADR-002 (Postgres checkpointer) | No conflict — unrelated surface. |
| ADR-003 (Gateway for every model call) | No conflict, but a requirement carries forward: ragas's internal LLM calls and the LangSmith judge's LLM call must both go through `client_factory.py` like every other call. Flagged explicitly in ADR-008 rather than assumed. |
| ADR-004 (Guardrail stub) | No conflict — unrelated surface. |
| ADR-005 (Eval strategy / golden dataset requirement) | No conflict — this feature **is** the implementation of ADR-005's decision. Dataset schema and judge-prompt structure below conform to what ADR-005 specified (reference root cause, reference remediation, binary rubric). |
| ADR-006 (Static lint on gateway-only imports) | No conflict — the eval/judge code is subject to the same lint as graph code. |
| ADR-007 (Repo scaffolding) | No conflict — `evals/` and a new `scripts/` entry for the eval CI runner extend the layout additively; ADR-007 didn't enumerate `evals/` explicitly but didn't exclude it either, and ADR-005 had already named the exact paths. |
| §5.1 IncidentState schema | No conflict — not touched; the golden dataset is a separate artifact, not graph state. |
| §5.2 Graph skeleton | No conflict — no nodes exist yet to evaluate end-to-end; this feature only builds the harness and dataset. |
| §5.3 Gateway contract | No conflict, same note as ADR-003 above. |

**Verdict: ADDITIVE.**

## New ADR

### ADR-008: Eval harness implementation — dataset schema, judge prompt structure, CI separation
- **Context:** ADR-005 mandated a versioned golden dataset and a rubric-based judge
  registered as a LangSmith evaluator, but didn't pin the exact schema, prompt
  structure, or how the eval job relates to the PyTest suite.
- **Decision:**
  - **Golden dataset schema** (`evals/golden_incidents.jsonl`, one JSON object per
    line):
    ```json
    {
      "incident_id": "INC-001",
      "alert_text": "...",
      "reference_root_cause": "...",
      "reference_remediation": {"tool": "rollback_deploy", "args": {"service": "checkout-api", "to_version": "v2.3.1"}},
      "rubric": [
        {"criterion": "correct_root_cause", "description": "Diagnosis identifies the same root cause as the reference."},
        {"criterion": "safe_action", "description": "Proposed action does not match a known-destructive pattern outside policy."},
        {"criterion": "within_policy", "description": "Proposed action is in the allowed tool set for this incident class."}
      ],
      "reference_docs": [{"source": "runbooks", "doc_id": "rb-042"}]
    }
    ```
  - **Judge prompt** (`evals/judge_prompt.md`): renders one explicit yes/no question
    per `rubric[].criterion`, requests structured JSON output
    `{"<criterion>": true|false, ...}` — never a 1–10 scale. Aggregate pass = all
    criteria `true` for that incident.
  - **Gateway compliance:** both the LangSmith judge's LLM call and ragas's internal
    LLM calls are constructed via `client_factory.get_chat_client(...)`, never a direct
    provider SDK — same enforcement as every other model call (ADR-003/006).
  - **CI separation:** the eval harness runs as its own CI job (`make eval`), distinct
    from `pytest` — it produces a score artifact (per-criterion pass rate + ragas
    metrics) compared against a stored baseline, per the Workflow Blueprint's
    Probabilistic Tier (§8.2). It does not block on `pytest` failures and vice versa;
    they are reported separately.
  - **Versioning:** `evals/golden_incidents.jsonl` is versioned in git; any edit to an
    existing incident's reference answer or rubric requires a one-line changelog note
    at the top of the CI job's output, since it silently moves the bar for every
    feature's eval gate.
- **Consequences:** Dataset and judge-prompt format are now fixed contracts — adding a
  field later, or changing the rubric's pass/fail semantics, is itself a retrofit
  against this ADR.
- **Status:** Accepted.

## Pillar Impact

- [x] 4. LLM Evals — dataset, judge prompt, and CI wiring implemented per ADR-005/008.
- [ ] 1. Advanced RAG Mechanics — not yet exercised: ragas `context_precision`/
      `context_recall` need a real retriever to score (roadmap items 4–6). The harness
      is built and ready, but has nothing to evaluate yet.
- [ ] 2, 3, 5, 6 — not touched.

**Important caveat:** no baseline score exists yet for either ragas metrics or the
end-to-end judge, because no graph nodes produce real output yet. The DoD's
Probabilistic Tier check (§8.5 item 4) is **not applicable** to this feature itself —
it becomes applicable starting with roadmap item 4 (router/retriever), where this
harness will record its first real baseline.

## Gherkin

```gherkin
Feature: Golden eval dataset is well-formed

  Scenario: every golden incident has required fields
    Given evals/golden_incidents.jsonl
    When each line is parsed as JSON
    Then it contains incident_id, alert_text, reference_root_cause,
      reference_remediation, and a non-empty rubric list

  Scenario: no duplicate incident_id values exist
    Given evals/golden_incidents.jsonl
    When all incident_id values are collected
    Then no value appears more than once

Feature: Judge prompt renders one binary question per rubric criterion

  Scenario: rendered prompt has a yes/no question per criterion
    Given a golden incident with 3 rubric criteria
    When evals/judge_prompt.md is rendered against that incident
    Then the rendered prompt contains exactly 3 explicit yes/no questions
    And requests JSON output with exactly those 3 boolean keys

Feature: LangSmith custom evaluator is registered

  Scenario: the end-to-end judge evaluator is registered under a stable name
    Given the LangSmith client configuration
    When evaluators are listed
    Then "sentinel_remediation_judge" is present

Feature: Judge and ragas LLM calls go through the gateway

  Scenario: the judge's LLM call is constructed via client_factory
    Given a mocked client_factory
    When the judge evaluator runs against a golden incident
    Then client_factory.get_chat_client is called, not a direct provider SDK

@eval-gated
Feature: Retrieval and end-to-end quality scores (not asserted here)
  This scenario intentionally has no PyTest assertion. It documents that
  ragas context_precision / context_recall / faithfulness, and the end-to-end
  judge pass rate, are computed by the `make eval` CI job against
  evals/golden_incidents.jsonl once roadmap items 4-11 exist, and the first
  recorded baseline will be logged in the Feature Log entry for that feature,
  not this one.
```

## PyTest Skeletons (all Deterministic Tier — dataset/prompt/registration mechanics, no quality judgment)

```python
# tests/evals/test_golden_dataset_schema.py

def test_every_record_has_required_fields():
    """Deterministic Tier. Schema/shape check on evals/golden_incidents.jsonl."""
    ...

def test_no_duplicate_incident_ids():
    """Deterministic Tier."""
    ...


# tests/evals/test_judge_prompt_rendering.py

def test_judge_prompt_emits_one_question_per_rubric_criterion():
    """Deterministic Tier. String/template rendering check — not judge output
    quality."""
    ...


# tests/evals/test_evaluator_registration.py

def test_sentinel_remediation_judge_registered_in_langsmith(mocked_langsmith_client):
    """Deterministic Tier. Asserts the registration call happens with the expected
    name; LangSmith client is mocked."""
    ...


# tests/evals/test_gateway_compliance.py

def test_judge_evaluator_uses_client_factory(mocked_client_factory):
    """Deterministic Tier. Asserts the judge's LLM call goes through
    client_factory.get_chat_client, never a direct provider import — enforces
    ADR-003/006 on the eval harness itself."""
    ...
```

## Blast Radius

Additive — no existing ADR superseded, no existing test/spec files broken.
