# Feature 13 — Guardrail Unstubbing (Real Llama Guard 3-8B Inference)

**Phase introduced:** Phase 4
**Status:** Done
**PMA sections touched:** ADR-019 (new, retrofit), §5.1, §8.3 (correction), §3 Pillar
3, §3 Pillar 4, §7 (resolves Open Question #1, new Open Question), §6 Feature Log, §9
item 13

## Feature Description

Replace the `guardrail_check()` stub with real Llama Guard 3-8B inference behind the
gateway, for both input and output moderation paths.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001, ADR-002 | No conflict — no graph/checkpointer surface touched. |
| ADR-003 (Gateway) | No conflict — real Llama Guard inference goes through `client_factory.get_chat_client(model="sentinel-guardrail")`, the same alias-based pattern Feature 12 (ADR-018) established, including fallback-to-secondary-safety-model config. |
| **ADR-004 (Guardrail stub, original text)** | **Minor conflict found:** ADR-004's own text says "Pillar 4 of the Production RAG Blueprint tracks unstubbing it" — but Pillar 4 is Evals, not Guardrails (Pillar 3). The actual tracking mechanism that exists is Open Question #1 (§7), not Pillar 4. This is a stale cross-reference from the original Phase 1 draft, not a substantive decision being reversed. Corrected below. |
| ADR-005 (Eval strategy) | No conflict, but a real gap surfaces: ADR-005's golden dataset and judge prompt cover remediation correctness, not guardrail moderation *accuracy* — yet §8.2 already named "guardrail moderation accuracy" as a Probabilistic Tier surface. Without a dataset, that promise is unfulfilled. Filled additively below (a new, separate eval artifact — does not touch `golden_incidents.jsonl`'s fixed schema). |
| ADR-006 (Lint) | No conflict — `guardrail_check()`'s internal LLM call still only goes through `client_factory`. |
| ADR-007 (Scaffolding) | No conflict — `guardrail_check()`'s location (`src/guardrails/check.py`) is unchanged; only its body changes from a hardcoded return to a real model call. |
| ADR-008 (Eval harness schema) | No conflict — the new guardrail red-team dataset is a separate file (`evals/guardrail_redteam.jsonl`), not a modification of `golden_incidents.jsonl`'s schema, which ADR-008 declared a fixed contract. |
| ADR-009, ADR-014 (guardrail routing) | No conflict — both call sites already route purely on `verdict == "unsafe"` vs not; real inference fills in real verdicts using the exact same binary contract, no routing change needed. |
| ADR-010 through ADR-018 | No conflict — unrelated surfaces. |
| §5.1 IncidentState schema | No conflict on the field's existence (`guardrail_input_verdict`/`guardrail_output_verdict: Optional[dict]`) — gap: the `GuardrailVerdict` dict's exact shape was named in ADR-004/007's prose (`verdict`, `reason`) but never formally pinned the way ADR-011/013 pinned other dicts. Filled additively below, with one new optional field. |
| §5.2 Graph skeleton | No conflict — both call sites' conditional edges are unchanged; only `guardrail_check()`'s internals change. |
| **§8.3 Gherkin conventions (Phase 2 Development Workflow Blueprint)** | **Conflict found:** the `@guardrail` convention's example text says verdicts are mocked as "`safe`/`unsafe`/`borderline`" — but no ADR has ever defined a `borderline` verdict or any routing behavior for it; every guardrail ADR (004, 009, 014) is strictly binary. This is a stale aspiration from Phase 2, never implemented or revisited. Resolved below: v1 stays binary; the prose is corrected. |
| §5.3 Gateway contract | No conflict, same note as ADR-003. |

**Verdict: RETROFIT** — two stale cross-references/prose mismatches (ADR-004's wrong
pillar reference; §8.3's unimplemented `borderline` verdict) are corrected as part of
this feature, alongside the additive real-inference capability and new eval dataset.
Neither correction reverses a decision anyone built against — `borderline` routing was
never implemented, and nothing depended on ADR-004's incorrect pillar reference.

## New ADR (Retrofit)

### ADR-019: Real Llama Guard 3-8B inference; `GuardrailVerdict` shape; guardrail eval dataset; corrects ADR-004's pillar reference and §8.3's `borderline` mention
- **Context:** `guardrail_check()` has returned a hardcoded `safe` verdict since
  Feature 01. Replacing it with real inference requires pinning the verdict's exact
  shape, deciding how moderation *accuracy* (as opposed to trigger-wiring) gets
  measured, and resolving two latent prose inconsistencies discovered during this
  feature's conflict check.
- **Decision:**
  - **Real inference:** `guardrail_check(text, direction)` now calls
    `client_factory.get_chat_client(model="sentinel-guardrail")` — a new LiteLLM
    model alias (ADR-018's pattern) backed by Llama Guard 3-8B, with a configured
    fallback safety model for proxy resilience.
  - **`GuardrailVerdict` shape** (formalizing `guardrail_input_verdict`/
    `guardrail_output_verdict: Optional[dict]`):
    `{"verdict": Literal["safe", "unsafe"], "reason": str, "category": Optional[str]}`
    — `category` holds Llama Guard's taxonomy code (e.g. `"S1"`) when unsafe, `None`
    when safe. Verdict stays strictly binary — no `borderline` state.
  - **Cache eligibility:** guardrail calls are normal `sentinel-app` traffic under
    ADR-018 and are cache-eligible like any other application call; they are
    deliberately *not* added to the eval-harness no-cache carve-out, since guardrail
    verdicts are not the thing being scored against a baseline the way eval-harness
    output is.
  - **New eval artifact (`evals/guardrail_redteam.jsonl`):** a versioned set of
    labeled safe/unsafe text examples (adversarial prompts, benign alerts/postmortems)
    with a `expected_verdict` field. A small precision/recall scorer runs in the same
    `make eval` CI job, measuring real moderation accuracy — the Probabilistic Tier
    surface §8.2 had already named but never had a dataset for. This is a new file,
    not a change to `golden_incidents.jsonl`'s schema (ADR-008 remains untouched).
  - **Correction to ADR-004:** "Pillar 4" is corrected to refer to Open Question #1
    (§7), the actual tracking mechanism; Pillar 4 (Evals) is unrelated to guardrail
    unstubbing itself, though it is where moderation *accuracy* measurement now lives
    (the new dataset above).
  - **Correction to §8.3:** the `@guardrail` convention's "safe/unsafe/borderline"
    example is corrected to "safe/unsafe" — `borderline` was never implemented and is
    not part of v1's contract. If a future feature wants a three-valued verdict, that
    is its own retrofit against this ADR, not a silent reinterpretation of an old
    example.
- **Consequences:** Resolves Open Question #1. `GuardrailVerdict`'s shape is now a
  fixed contract — adding fields to it later is additive, but removing the binary
  constraint is a retrofit. Guardrail moderation accuracy is measurable for the first
  time, with thresholds to be tuned (new Open Question).
- **Status:** Accepted.

## Blast Radius

- **ADR-004 corrected** (wrong pillar cross-reference) — no decision reversed, only a
  stale reference fixed.
- **§8.3 corrected** (`borderline` removed from the example) — no test or
  implementation ever depended on a three-valued verdict, so nothing breaks; this
  only prevents a future feature from building against a contract that was never
  real.
- **Open Question #1 resolved** — marked `Resolved by ADR-019` in §7, not deleted.
- No existing test/spec file breaks — `guardrail_check()`'s call sites (Features 03,
  08, 11) only ever asserted routing behavior against mocked verdicts, never against
  the stub's hardcoded `safe` value itself, so swapping the implementation underneath
  is invisible to those tests by design (per §8.3's mocking convention).

## Pillar Impact

- [x] 3. Guardrails — real Llama Guard 3-8B inference now backs both call sites;
      `GuardrailVerdict`'s shape is formalized with a `category` field for audit.
- [x] 4. LLM Evals — new `evals/guardrail_redteam.jsonl` + precision/recall scorer
      gives Pillar 3's "accuracy" surface (already named in §8.2) a real dataset for
      the first time.
- [ ] 1, 2, 5, 6 — not touched.

## Gherkin

```gherkin
@guardrail
Feature: guardrail_check performs real Llama Guard inference

  Scenario: an adversarial input is classified unsafe with a category
    Given a red-team input known to violate a Llama Guard taxonomy category
    When guardrail_check(text, direction="input") runs against the real model
    Then the verdict is "unsafe"
    And category is a non-empty taxonomy code

  Scenario: a benign alert is classified safe
    Given a benign alert text from evals/guardrail_redteam.jsonl
    When guardrail_check(text, direction="input") runs against the real model
    Then the verdict is "safe"
    And category is null

  Scenario: guardrail_check still only calls through the gateway
    Given a mocked client_factory
    When guardrail_check runs
    Then client_factory.get_chat_client(model="sentinel-guardrail") is called,
      never a direct provider SDK

  Scenario: guardrail calls are cache-eligible, unlike eval harness calls
    Given a repeated identical guardrail_check call
    When the second call is made
    Then no cache={"no-cache": true} override is present, distinguishing it from
      eval harness traffic (ADR-018)
```

## PyTest Skeletons (mixed tiers — see annotations; moderation *accuracy* moves to the Probabilistic Tier via the new red-team dataset, never asserted with `==` in PyTest)

```python
# tests/guardrails/test_guardrail_check.py

def test_guardrail_check_uses_client_factory(mock_client_factory):
    """Deterministic Tier. Enforces ADR-003/006/019's gateway-only call path."""
    ...

def test_guardrail_verdict_shape_is_well_formed(mock_client_factory):
    """Deterministic Tier. Asserts the GuardrailVerdict dict has verdict/reason/
    category keys with correct types — not whether the verdict is *correct*."""
    ...

def test_guardrail_calls_do_not_set_no_cache(mock_client_factory):
    """Deterministic Tier. Distinguishes guardrail traffic from eval-harness traffic
    per ADR-018/019's cache-eligibility decision."""
    ...


# evals/run_guardrail_eval.py (Probabilistic Tier, run via `make eval`, not pytest)
# Scores guardrail_check's real verdicts against evals/guardrail_redteam.jsonl's
# expected_verdict field; reports precision/recall against a versioned baseline.
# Never asserted with `assert ==` — gated by threshold comparison, same pattern as
# ragas/sentinel_remediation_judge (ADR-005/008).
```

## Implementation Status

**What was built:**
- `src/guardrails/check.py` rewritten: `guardrail_check(text, direction)` now calls
  `client_factory.get_chat_client(model="sentinel-guardrail")`, parses a strict-JSON
  response, and returns the formalized `GuardrailVerdict` TypedDict
  (`verdict`/`reason`/`category`). A new `GuardrailCheckError` is raised — never a
  silent "safe" default — on non-JSON responses, an invalid `verdict`, a missing/empty
  `reason`, or a `verdict`/`category` mismatch (safe must have `category=None`, unsafe
  must have a non-empty category).
- `infra/litellm_config.yaml`: removed the "reserved, not yet called" comments on the
  `sentinel-guardrail` model alias (entries themselves pre-existed from Feature 12).
- `src/graph/nodes/guardrail_input.py` / `guardrail_output.py`: docstrings updated to
  describe real inference; no routing logic changed (both only ever read
  `verdict["verdict"]`, confirmed by grep before editing).
- New eval artifact `evals/guardrail_redteam.jsonl` (10 labeled examples, mixed
  safe/unsafe and input/output) plus its loader/validator
  (`src/evals/guardrail_dataset.py`, `GuardrailDatasetError`) and a confusion-matrix
  precision/recall scorer (`src/evals/guardrail_eval.py`, `score_guardrail_dataset`).
- `scripts/run_eval.py` extended to load/validate the red-team dataset as part of
  `make eval`'s mechanics-only run, printing a status line and an explicit caveat that
  moderation-accuracy scoring against a real model isn't possible in this sandbox
  (no live LiteLLM proxy/PyPI egress — same constraint as Open Question #15).
- New tests: `tests/guardrails/test_check.py` (7 tests, Deterministic Tier, gateway
  call contract + verdict shape + cache-eligibility + error paths, `client_factory`
  mocked throughout — never asserts a verdict is *correct*),
  `tests/evals/test_guardrail_dataset_schema.py` (7 tests),
  `tests/evals/test_guardrail_eval_scorer.py` (3 tests).

**Deviations from spec:**
- The spec's named skeleton file was `tests/guardrails/test_guardrail_check.py`; the
  actual file is `tests/guardrails/test_check.py` (matching this repo's existing
  `tests/<package>/test_<module>.py` naming convention, since the module is
  `src/guardrails/check.py`). Same 3 named test cases plus 4 supplementary ones
  (safe-has-null-category, unsafe-with-no-category-raises, invalid-verdict-raises,
  non-JSON-response-raises) — broader coverage, no narrower.
- `evals/run_guardrail_eval.py` (spec's named Probabilistic Tier entry point) was not
  created as a separate script; instead `score_guardrail_dataset` was wired directly
  into the existing `scripts/run_eval.py` (`make eval`'s single entry point), since a
  second script would have duplicated dataset-path/CLI plumbing for no benefit. The
  scorer function itself lives at `src/evals/guardrail_eval.py` exactly as specified.

**Blast radius confirmed:** all 168 tests pass, including the existing graph-level
integration tests (`tests/graph/test_skeleton.py`,
`tests/graph/test_hitl_checkpoint_restart.py`) — those tests construct
`guardrail_output_verdict` dicts that don't include a `category` key, which is fine
since `category` is additive and nothing reads it yet. Three of those integration
tests previously relied on the *old stub's* hardcoded "safe" return for the
`guardrail_output` call site (they only ever patched `guardrail_input.guardrail_check`,
not `guardrail_output.guardrail_check`); since `guardrail_output` now calls the same
real `guardrail_check()` that requires a configured gateway, those three tests needed
a new `@patch("src.graph.nodes.guardrail_output.guardrail_check")` added — a test-only
fix, no production code or ADR decision changed.

**New Open Question confirmed, not invented:** Open Question #13 in §7
(guardrail moderation precision/recall thresholds are placeholders) was already
pre-flagged in the PMA before this feature started, consistent with the Feature 11/12
pattern — no new Open Question number was added.

**Verification:**
- `python -m unittest discover -s tests -p "test_*.py"` → 168/168 passing.
- `bash scripts/lint_gateway_usage.sh` → PASS (no direct provider SDK usage).
- `python scripts/run_eval.py` → PASS (golden dataset + guardrail red-team dataset
  both schema-valid; harness mechanics only, no live-model baseline, as expected).

**Definition of Done:**
- [x] Spec's Conflict Check verified still holds (no re-derivation needed).
- [x] Real-inference implementation matches ADR-019.
- [x] Tests written and passing (Deterministic Tier for shape/contract; Probabilistic
      Tier scorer exists and is unit-tested on its own arithmetic, ready for a live
      model once sandbox constraints lift).
- [x] Lint and eval harness both green.
- [x] Feature file Status → Done, this section appended.
- [x] PROJECT_MEMORY.md updated (ADR-019 implementation-status bullet, Feature Log
      row, §9 checkbox, Open Question #1 resolution marker, ADR-004/§8.3 corrections).
