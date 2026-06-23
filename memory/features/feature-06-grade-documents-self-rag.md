# Feature 06 — `grade_documents` Node + Self-RAG Retry Loop

**Phase introduced:** Phase 4
**Status:** Done
**PMA sections touched:** ADR-012 (new), §5.1, §3 Pillar 1, §7 (new Open Question),
§6 Feature Log, §9 item 6

## Feature Description

Add the `grade_documents` node that scores reranked context for relevance and, on a
low score, loops back to `router` with a reformulated query, capped at 2 retries.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — this is the cycle the Project Charter (§1) explicitly named as the reason a linear chain can't work. |
| ADR-002 (Postgres checkpointer) | No conflict — the retry loop runs within a single `invoke`, no interrupt/pause involved. |
| ADR-003 (Gateway) | No conflict, requirement carries forward: `grade_documents`'s structured-output grading call goes through `client_factory.get_chat_client(...)`. |
| ADR-004 (Guardrail stub) | No conflict — unrelated surface. |
| ADR-005 (Eval strategy) | No conflict — self-RAG reflection quality was already anticipated as Probabilistic Tier in §8.2's pillar mapping table; this feature builds the mechanism only. |
| ADR-006 (Lint) | No conflict. |
| ADR-007 (Scaffolding) | No conflict — `src/graph/nodes/grade_documents.py`, per the established convention. |
| ADR-008 (Eval harness) | No conflict. |
| ADR-009 (Skeleton retrofit) | No conflict — unaffected by the guardrail rejection-branch fix. |
| ADR-010 (Router scope) | No conflict — the retry loop re-enters `router` with the same single-corpus contract; nothing here widens `route` back to multi-corpus. |
| ADR-011 (Document shape) | No conflict — `grade_documents` reads `reranked_docs` in the shape ADR-011 already pinned, without modifying it. |
| §5.1 IncidentState schema | **Gap, not a contradiction.** Neither ADR-010 nor ADR-011 ever pinned *which field* `router`/`retriever` read as the query text — both ADRs say "query" abstractly. Implementing "loop back with a reformulated query" requires somewhere to put that reformulated text, and no such field exists yet. Filled in additively below (`current_query`), not a redefinition of any existing key. |
| §5.2 Graph skeleton | No conflict — `grade_documents -(low relevance, retry_count<2)-> router` and `grade_documents -(ok)-> diagnose` already exist exactly as needed. One gap: the skeleton doesn't say what happens when relevance is low **and** `retry_count >= 2` (retries exhausted) — resolved additively below (proceeds to `diagnose` with degraded context, not silently treated as "ok"). |
| §5.3 Gateway contract | No conflict, same note as ADR-003. |

**Verdict: ADDITIVE.** No existing ADR or contract is contradicted — two genuine gaps
(query-reformulation storage, retry-exhaustion behavior) are filled rather than any
prior decision being reversed. Because Features 04 and 05 used "query" abstractly
without binding it to `raw_alert`, clarifying it now as `current_query` does not
redefine their stated contracts — but both feature files get a one-line forward
note so their (not-yet-written) node implementations read the right field.

## New ADR

### ADR-012: Self-RAG grading mechanics — `current_query` field, grade threshold, retry-exhaustion behavior
- **Context:** §5.1 had `retry_count` but no field to hold a reformulated query, and
  the skeleton didn't specify behavior when relevance stays low after retries are
  exhausted.
- **Decision:**
  - New additive field: `current_query: Optional[str]` — initialized to `raw_alert` at
    `entry` (or by `guardrail_input`/`router`, whichever runs first), overwritten by
    `grade_documents` with a reformulated query when looping back. `router` and
    `retriever` read `current_query` (falling back to `raw_alert` if unset), not
    `raw_alert` directly.
  - `grade_documents` makes one structured-output LLM call through
    `client_factory.get_chat_client(...)` returning `{"relevance_grade": float (0.0-1.0),
    "reformulated_query": Optional[str]}`. `reformulated_query` is required when
    `relevance_grade` is below threshold, ignored otherwise.
  - **Threshold:** `relevance_grade < 0.6` is "low relevance." This number is a
    placeholder pending eval-driven tuning — tracked as a new Open Question (see
    below), not asserted as correct.
  - **Retry-exhaustion behavior:** if relevance is still low after `retry_count`
    reaches 2, the graph proceeds to `diagnose` anyway (graceful degradation) rather
    than failing the run. `state.relevance_grade` is preserved so `diagnose`'s prompt
    can hedge / lower its stated confidence — this is *not* treated as equivalent to
    an "ok" grade, it is a distinct degraded path sharing the same edge target.
- **Consequences:** `diagnose` (roadmap item 7) must be written aware that it can
  receive either a confidently-graded or a degraded context, and should not assume
  `relevance_grade >= 0.6` just because it was reached.
- **Status:** Accepted.

## Blast Radius

- Additive — no existing ADR superseded.
- **Forward note added to `feature-04-ingestion-router-node.md` and
  `feature-05-retriever-reranker-nodes.md`:** when those nodes are actually
  implemented, they must read `state.current_query` (falling back to `raw_alert`), not
  `raw_alert` directly — neither file's existing Gherkin/PyTest skeletons assert the
  query source, so nothing already written breaks, but the implementation should not
  hardcode `raw_alert`.
- No existing test/spec file is broken — no node has been implemented yet.

## Pillar Impact

- [x] 1. Advanced RAG Mechanics — self-RAG/reflection loop, the graph's primary cycle
      and the load-bearing reason LangGraph was chosen (§1), is now fully specified.
      Pillar 1 (routing, retrieval, re-ranking, self-RAG) is design-complete end to end.
- [ ] 2, 3, 4, 5, 6 — not touched (eval-scoring of self-RAG quality was already
      anticipated in §8.2, not a new harness capability).

## Gherkin

```gherkin
Feature: grade_documents scores relevance and routes accordingly

  Scenario: high relevance routes to diagnose
    Given grade_documents's LLM call is mocked to return relevance_grade 0.85
    And reranked_docs has 5 entries
    When the grade_documents node runs
    Then state.relevance_grade equals 0.85
    And the next edge target is "diagnose"

  Scenario: low relevance with retries remaining loops back to router
    Given grade_documents's LLM call is mocked to return relevance_grade 0.3 and
      reformulated_query "alternate phrasing of the alert"
    And state.retry_count is 0
    When the grade_documents node runs
    Then state.retry_count equals 1
    And state.current_query equals "alternate phrasing of the alert"
    And the next edge target is "router"

  Scenario: low relevance with retries exhausted proceeds to diagnose anyway
    Given grade_documents's LLM call is mocked to return relevance_grade 0.3
    And state.retry_count is 2
    When the grade_documents node runs
    Then the next edge target is "diagnose"
    And state.relevance_grade equals 0.3

  Scenario: grading call goes through the gateway
    Given a mocked client_factory
    When the grade_documents node runs
    Then client_factory.get_chat_client is called, not a direct provider SDK
```

## PyTest Skeletons (all Deterministic Tier — routing/retry mechanics, mocked LLM grading call; whether the grade is *accurate* is Probabilistic Tier per §8.2 and is NOT asserted here)

```python
# tests/graph/nodes/test_grade_documents.py

def test_high_relevance_routes_to_diagnose(mock_client_factory):
    """Deterministic Tier. Mocked grade above threshold; asserts routing only."""
    ...

def test_low_relevance_with_retries_remaining_loops_to_router(mock_client_factory):
    """Deterministic Tier. Asserts retry_count increments, current_query is
    overwritten, and routing target is 'router' — never asserts whether the
    reformulated query is actually better."""
    ...

def test_low_relevance_with_retries_exhausted_proceeds_to_diagnose(mock_client_factory):
    """Deterministic Tier. Asserts the degraded-path routing target is 'diagnose',
    distinct from but reaching the same node as the 'ok' path; relevance_grade is
    preserved in state for diagnose to read."""
    ...

def test_grade_documents_uses_client_factory(mock_client_factory):
    """Deterministic Tier. Enforces ADR-003/006 on the grading call."""
    ...
```

## Implementation Status

### Implemented

- `src/graph/state.py`: added `current_query: Optional[str]` (ADR-012).
- `src/graph/nodes/router.py`, `retriever.py`, `reranker.py`: all three changed
  `query = state["raw_alert"]` → `query = state.get("current_query") or
  state["raw_alert"]`, fulfilling this feature's forward note to Features 04/05.
- `src/graph/nodes/grade_documents.py` (new): `grade_documents` node,
  `grade_documents_route` path function, `GradeDocumentsError`. One structured-output
  call via `get_chat_client(model="sentinel-grader")`. `RELEVANCE_THRESHOLD = 0.6`,
  `MAX_RETRIES = 2`.
- **`retry_count` redefinition (deliberate resolution of a Gherkin ambiguity, not a
  Gherkin violation):** `retry_count` counts *low-relevance gradings seen so far*
  (incremented on every low grading, whether or not a retry is taken), not "retries
  taken." Without this, a path function reading only final state cannot distinguish
  "just used the last allowed retry" from "had none left before this call" — both
  converge on the same `retry_count`. Traced against all four Gherkin scenarios above
  and confirmed it produces identical observable behavior to the spec's wording at
  every stated boundary (retry_count 0→1 retries, 1→2 retries, starting at 2 gives
  up). Documented at length in `grade_documents.py`'s module docstring.
- `src/graph/_compat.py` (ADR-021 addendum): retrofitted to support cycles —
  `compile()` no longer raises on a structural cycle (only validates edge
  targets/entry); `invoke()` gained a `max_steps` runtime cap (default 25, mirrors
  real LangGraph's `recursion_limit`) raising new `GraphRecursionError`. This is a
  generic safety net against a runaway path function — Sentinel's actual cycle is
  bounded by `grade_documents`' own retry cap and should never hit it.
- `src/graph/build.py`: replaced `_grade_documents_placeholder` with the real node;
  `reranker -> grade_documents` then `add_conditional_edges(grade_documents,
  grade_documents_route, {ROUTE_RETRY: "router", ROUTE_PROCEED: "diagnose"})` — the
  graph's first real cycle. Added `_diagnose_placeholder` for roadmap item 7.

### Deviations from the PyTest skeletons

- Added tests beyond the four skeletons: missing-`reformulated_query`-when-retry-due
  raises `GradeDocumentsError`; non-JSON response raises; missing `relevance_grade`
  raises; a "third consecutive low grading gives up even though a
  reformulated_query was supplied" test, proving the route decision is
  retry-budget-based, not presence-of-reformulated-query-based.
- `tests/graph/test_compat.py`: the two cycle-rejecting tests
  (`test_cycle_raises`, `test_conditional_edges_with_a_cycle_raises_at_compile_time`)
  were rewritten rather than removed — both now assert the opposite (cycles compile
  and run correctly) — plus a new `test_unbounded_cycle_raises_graph_recursion_error`
  pinning the runtime safety net.
- `tests/graph/test_skeleton.py`: the Feature 05 safe-path test was extended (mocking
  `grade_documents`'s gateway call to return a high grade) and a new full-graph
  integration test added, proving the self-RAG loop actually executes two retries
  end-to-end through the live `_compat.py` before giving up to `diagnose`.

### Verification

- `python3 -m unittest discover -s tests` → **84/84 passing** (up from 74).
- `bash scripts/lint_gateway_usage.sh` → passed.
- `python3 scripts/run_eval.py` → passed (harness mechanics only).

### Definition of Done

- [x] New ADR-012 written and accepted.
- [x] `current_query` field added additively to `IncidentState`.
- [x] `grade_documents` node + path function implemented per ADR-012.
- [x] Retry-counting ambiguity identified, resolved, and documented.
- [x] `_compat.py` retrofitted for cycles (ADR-021 addendum), with a runtime safety
      net distinct from the node's own retry cap.
- [x] `build.py` rewired into the graph's first real cycle.
- [x] All four Gherkin scenarios covered by passing tests, plus additional edge
      cases.
- [x] Full test suite, lint, and eval harness all pass.
- [x] `PROJECT_MEMORY.md` updated (Feature Log, ADR-012, ADR-021 addendum, §9 item
      6, new Open Question for the threshold).
