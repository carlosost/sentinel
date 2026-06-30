# Feature 07 — `diagnose` + `propose_action` Nodes

**Phase introduced:** Phase 4
**Status:** Done
**PMA sections touched:** ADR-013 (new), §5.1, §3 Pillar 1, §3 Pillar 2, §3 Pillar 4,
§7 (new Open Question), §6 Feature Log, §9 item 7

## Feature Description

Add the `diagnose` and `propose_action` nodes: generate a root-cause diagnosis from
graded context, then produce a structured `{tool, args}` remediation proposal.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — sequential nodes after `grade_documents`, per the skeleton. |
| ADR-002 (Postgres checkpointer) | No conflict — no interrupt here; that's `await_human_approval` (roadmap item 9). |
| ADR-003 (Gateway) | No conflict, requirement carries forward: both `diagnose` and `propose_action` LLM calls go through `client_factory.get_chat_client(...)`. |
| ADR-004 (Guardrail stub) | No conflict — `propose_action -> guardrail_output` per the skeleton; `guardrail_output` itself is roadmap item 8 and isn't built yet, which is expected sequencing, not a blocker. |
| ADR-005 (Eval strategy) | No conflict — this is the first feature where `sentinel_remediation_judge` (ADR-008) has real `diagnosis`/`proposed_action` output to score against `golden_incidents.jsonl`'s reference fields. |
| ADR-006 (Lint) | No conflict. |
| ADR-007 (Scaffolding) | No conflict — `src/graph/nodes/diagnose.py`, `src/graph/nodes/propose_action.py`, plus a new `src/tools/registry.py` (gap, filled below). |
| ADR-008 (Eval harness) | No conflict — same note as ADR-005. |
| ADR-009 (Skeleton retrofit) | No conflict. |
| ADR-010 (Router scope) | No conflict. |
| ADR-011 (Document shape) | No conflict — `diagnose` reads `reranked_docs` in the pinned shape without modifying it. |
| ADR-012 (Self-RAG mechanics) | No conflict, but a requirement carries forward: ADR-012 explicitly said `diagnose` "must not assume `relevance_grade >= 0.6`." This feature must honor that, not just avoid contradicting it — addressed via a new `diagnosis_confidence` field below. |
| §5.1 IncidentState schema | **Gap, not a contradiction.** `proposed_action: Optional[dict]` was declared as `{"tool": str, "args": dict}` only — but §5.2's `guardrail_output` branches on whether the chosen tool is "side_effecting" or "read-only," and nothing in the schema or anywhere else records that classification per-tool. Filled in additively below (a static tool registry + a `side_effecting` field on `proposed_action`). |
| §5.2 Graph skeleton | No conflict on edges (`diagnose -> propose_action -> guardrail_output` matches). One latent gap noticed: the skeleton's `guardrail_output -(read-only action)-> execute` branch requires at least one read-only tool to exist, or that edge is dead code forever — addressed below by seeding the registry with one read-only tool. Also noted: `diagnose` is re-entered from `await_human_approval -(rejected)-> diagnose` and `execute -(failure)-> diagnose` (roadmap items 9–10) — this feature scopes `diagnose` to the first-pass case only; re-entry handling is deferred (new Open Question below), not solved here. |
| §5.3 Gateway contract | No conflict, same note as ADR-003. |

**Verdict: ADDITIVE.** No existing ADR or contract is contradicted — gaps are filled
(tool registry/`side_effecting` flag, confidence hedging field), and one piece of
scope (diagnose re-entry) is explicitly deferred rather than solved ambiguously.

## New ADR

### ADR-013: `proposed_action` shape with `side_effecting` flag; tool registry; diagnosis confidence hedging
- **Context:** §5.2's HITL/execute branching depends on knowing whether a tool is
  side-effecting, but no registry or per-action flag existed. Separately, ADR-012
  required `diagnose` to not assume high relevance just because it was reached, but
  gave no mechanism for expressing reduced confidence in a way later nodes could read
  without parsing free text.
- **Decision:**
  - **Tool registry** (`src/tools/registry.py`): a static
    `dict[str, {"side_effecting": bool}]`, seeded with:
    `restart_service` (side_effecting=True), `rollback_deploy` (side_effecting=True),
    `page_secondary_oncall` (side_effecting=True), `fetch_additional_logs`
    (side_effecting=False) — the last one exists specifically so §5.2's read-only
    branch (`guardrail_output -(read-only action)-> execute`) is reachable at all.
  - **`proposed_action` shape** (§5.1, amended): `{"tool": str, "args": dict,
    "side_effecting": bool}` — `propose_action` looks up `side_effecting` from the
    registry by tool name and embeds it, so `guardrail_output`/`await_human_approval`
    (roadmap items 8–9) never re-derive the classification.
  - **Diagnosis confidence:** new additive field `diagnosis_confidence:
    Optional[Literal["high", "low"]]` on `IncidentState`. `diagnose` sets it to `"low"`
    whenever `relevance_grade < 0.6` (ADR-012's threshold) or retries were exhausted
    with a still-low grade; `"high"` otherwise. This is a structured signal, not a
    free-text hedge, so later nodes and Deterministic Tier tests can branch/assert on
    it without inspecting `diagnosis` text content.
  - `diagnose` and `propose_action` are each one structured-output LLM call through
    `client_factory.get_chat_client(...)`.
- **Consequences:** `guardrail_output`/`await_human_approval`/`execute` (roadmap items
  8–10) can rely on `proposed_action["side_effecting"]` and
  `state.diagnosis_confidence` as fixed contracts; changing either later is a retrofit
  against this ADR.
- **Status:** Accepted.

## Blast Radius

Additive — no existing ADR superseded, no existing test/spec files broken.

## Pillar Impact

- [x] 1. Advanced RAG Mechanics — `diagnose` is the "generation" step Pillar 1's
      original prose pointed to but never detailed as its own bullet; now specified.
- [x] 2. Human-in-the-Loop — groundwork only: `proposed_action.side_effecting` now
      exists for `await_human_approval` (roadmap item 9) to branch on. The interrupt
      node itself is not built yet — this is preparatory, not a claim that HITL is
      implemented.
- [x] 4. LLM Evals — `sentinel_remediation_judge` (ADR-008) can now run meaningfully
      for the first time: `diagnosis` and `proposed_action` exist to compare against
      `golden_incidents.jsonl`'s `reference_root_cause`/`reference_remediation`. First
      baseline recorded once this feature's code lands, not yet at design stage.
- [ ] 3, 5, 6 — not touched.

## Gherkin

```gherkin
Feature: diagnose produces a diagnosis and a confidence signal

  Scenario: high relevance produces high-confidence diagnosis
    Given diagnose's LLM call is mocked to return a diagnosis string
    And state.relevance_grade is 0.85
    When the diagnose node runs
    Then state.diagnosis is non-empty
    And state.diagnosis_confidence equals "high"

  Scenario: degraded context (low relevance) produces low-confidence diagnosis
    Given diagnose's LLM call is mocked to return a diagnosis string
    And state.relevance_grade is 0.3
    When the diagnose node runs
    Then state.diagnosis_confidence equals "low"

  Scenario: diagnose's LLM call goes through the gateway
    Given a mocked client_factory
    When the diagnose node runs
    Then client_factory.get_chat_client is called, not a direct provider SDK

Feature: propose_action attaches side_effecting from the tool registry

  Scenario: a side-effecting tool is correctly flagged
    Given propose_action's LLM call is mocked to choose tool "rollback_deploy"
    When the propose_action node runs
    Then state.proposed_action equals {"tool": "rollback_deploy", "args": {...}, "side_effecting": true}

  Scenario: a read-only tool is correctly flagged
    Given propose_action's LLM call is mocked to choose tool "fetch_additional_logs"
    When the propose_action node runs
    Then state.proposed_action.side_effecting equals false

  Scenario: propose_action's LLM call goes through the gateway
    Given a mocked client_factory
    When the propose_action node runs
    Then client_factory.get_chat_client is called, not a direct provider SDK
```

## PyTest Skeletons (all Deterministic Tier — structural/contract mechanics, mocked LLM calls; diagnosis/remediation *quality* is Probabilistic Tier per §8.2 and is scored by `sentinel_remediation_judge`, not asserted here)

```python
# tests/graph/nodes/test_diagnose.py

def test_high_relevance_yields_high_confidence(mock_client_factory):
    """Deterministic Tier. Asserts diagnosis_confidence flag only, never the
    diagnosis text content."""
    ...

def test_low_relevance_yields_low_confidence(mock_client_factory):
    """Deterministic Tier. Enforces ADR-012's hedging requirement structurally."""
    ...

def test_diagnose_uses_client_factory(mock_client_factory):
    """Deterministic Tier. Enforces ADR-003/006 on the diagnose call."""
    ...


# tests/graph/nodes/test_propose_action.py

def test_side_effecting_tool_is_flagged_true(mock_client_factory, mock_tool_registry):
    """Deterministic Tier. Asserts the registry lookup is applied; never asserts
    whether the chosen tool is the 'right' remediation."""
    ...

def test_read_only_tool_is_flagged_false(mock_client_factory, mock_tool_registry):
    """Deterministic Tier. Confirms the read-only branch of §5.2 is reachable."""
    ...

def test_propose_action_uses_client_factory(mock_client_factory):
    """Deterministic Tier. Enforces ADR-003/006 on the propose_action call."""
    ...
```

## Implementation Status

### Implemented

- `src/tools/registry.py` (new): static `TOOL_REGISTRY` dict per ADR-013, seeded
  with the three side-effecting tools + `fetch_additional_logs` (read-only);
  `get_tool_spec`/`is_side_effecting` helpers; `UnknownToolError` raised on an
  unrecognized tool name.
- `src/graph/nodes/diagnose.py` (new): real node replacing
  `_diagnose_placeholder`. One structured-output call via
  `get_chat_client(model="sentinel-diagnose")`. `diagnosis_confidence` derived
  from `state.relevance_grade` against `grade_documents.RELEVANCE_THRESHOLD`
  (imported, not redefined, so the two thresholds cannot drift) — `"low"`
  whenever the grade is missing or below threshold (covers both the ordinary
  low-grade case and ADR-012's retry-exhaustion graceful-degradation path),
  `"high"` otherwise. `DiagnoseError` on missing/invalid response.
- `src/graph/nodes/propose_action.py` (new): real node. One structured-output
  call via `get_chat_client(model="sentinel-propose-action")` returning
  `{"tool": str, "args": dict}` only — `side_effecting` is always looked up
  from `src.tools.registry` by tool name afterward, never trusted from the LLM
  response even if present in its JSON (the feature's one new design decision
  beyond ADR-013's prose; documented in the module docstring). `args` defaults
  to `{}` if the response omits it. `ProposeActionError` on missing/invalid
  `tool`, on non-JSON response, or on an unknown tool name.
- `src/graph/state.py`: added `diagnosis_confidence: Optional[Literal["high",
  "low"]]` (ADR-013) — the one field §5.1 had already pinned but `state.py`
  itself hadn't caught up to yet.
- `src/graph/build.py`: replaced `_diagnose_placeholder` with the real
  `diagnose`/`propose_action` nodes; `diagnose -> propose_action ->
  guardrail_output`. Added `_guardrail_output_placeholder` for roadmap item 8.

### Deviations from the PyTest skeletons

- Added tests beyond the skeletons: non-JSON/missing-field error cases for both
  nodes; a dedicated test proving a forged `"side_effecting"` in the LLM
  response is ignored in favor of the registry lookup (the trust-boundary
  decision called out above); a registry test confirming at least one
  read-only tool exists (so §5.2's read-only `guardrail_output -> execute`
  branch is reachable at all, per this feature's own Conflict Check note).
- `tests/graph/test_skeleton.py`: both full-graph integration tests (high
  relevance and the self-RAG retry-exhaustion path) were extended with mocks
  for `diagnose`/`propose_action`'s gateway calls and now assert
  `diagnosis`/`diagnosis_confidence`/`proposed_action` reach their expected
  values at the end of a full run through `guardrail_output`'s placeholder.
- `scripts/run_eval.py`: its "no quality baseline yet" message referenced
  "retriever and diagnose/propose_action nodes" as not-yet-existing — now
  stale since this feature builds them. Updated to say the harness still
  needs to be wired to actually invoke the live graph against
  `golden_incidents.jsonl`, which is a separate, not-yet-scheduled piece of
  work.

### Verification

- `python3 -m unittest discover -s tests` → **101/101 passing** (up from 84).
- `bash scripts/lint_gateway_usage.sh` → passed.
- `python3 scripts/run_eval.py` → passed (harness mechanics only; no baseline
  recorded yet — see deviation note above).

### Definition of Done

- [x] ADR-013 (pre-drafted in docs/PROJECT_MEMORY.md) re-verified against the
      actual Feature 04-06 codebase and confirmed accurate — implemented as
      specified, with one additive trust-boundary decision documented.
- [x] Tool registry implemented with at least one read-only tool.
- [x] `diagnose`/`propose_action` nodes implemented per ADR-013.
- [x] `diagnosis_confidence` added to `IncidentState` (closing the
      scaffolding lag noted in this feature's Conflict Check).
- [x] `build.py` rewired; new placeholder added for roadmap item 8.
- [x] All Gherkin scenarios covered by passing tests, plus additional edge
      cases.
- [x] Full test suite, lint, and eval harness all pass.
- [x] `docs/PROJECT_MEMORY.md` updated (Feature Log, §9 item 7; ADR-013 and the
      Pillar 1/2/4 "Implementation status (Feature 07)" notes were already
      pre-drafted and required no correction).
