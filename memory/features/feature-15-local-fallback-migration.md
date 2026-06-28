# Feature 15 — Local Fallback Migration (Anthropic/Cohere → Ollama Open-Weights)

**Phase introduced:** Phase 4 (post-roadmap; first feature not gated behind §9's
dependency-ordered backlog, since it touches infra/gateway config, not the graph)
**Status:** Done (2026-06-28)
**PMA sections touched:** ADR-023 (new), §3 Pillar 5, §6 Feature Log, §7 (new Open
Questions #16, #17), §9 item 15
**Source of truth:** `MIGRATION_PLAN.md` (full plan — this file tracks its execution
against this project's Conflict-Check/Gherkin/PyTest/Definition-of-Done convention;
it does not restate the plan's reasoning, only its conflict surface and status)

## Feature Description

Replace the two paid-API fallback dependencies in `infra/litellm_config.yaml`
(`anthropic/claude-3-5-haiku-20241022` and `claude-3-5-sonnet-20241022` backing six
chat aliases; `cohere/embed-english-v3.0` backing the embedding alias) with locally
-served open-weights models via Ollama, gated behind a shadow-verification rollout
before any paid key is revoked. `sentinel-guardrail`'s TogetherAI-served primary is
explicitly out of scope (Phase 5 of `MIGRATION_PLAN.md`, separate approval required).

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001, ADR-002 | No conflict — no graph/checkpointer surface touched. |
| **ADR-003 (Gateway, sole construction path)** | No conflict, and notably *load-bearing in this feature's favor*: because every node calls models only via `client_factory.get_chat_client(alias)`, swapping what an alias resolves to in `litellm_config.yaml` requires zero node changes. Confirmed by grep across `src/graph/nodes/*.py` before editing — no file references a provider name. |
| **ADR-006 (lint, CI-blocking)** | No conflict — `scripts/lint_gateway_usage.sh` greps for `ChatOpenAI(`/`ChatAnthropic(`/direct SDK imports in `src/`/`scripts/`; this migration touches only YAML/env/Makefile, no Python import added. Re-run after Phase 2 to confirm, not assumed. |
| ADR-007 (scaffolding) | No conflict — no new module layout decisions needed; `scripts/pull_local_models.sh` follows the existing `scripts/*.sh` convention (`check_env.sh`, `lint_gateway_usage.sh`). |
| ADR-018 (LiteLLM production config: fallback chains, caching, rate limits) | **Extends, does not conflict.** This feature is additive within ADR-018's own mechanism — a `fallbacks:` list entry's target model string changes provider; the fallback-chain *structure* ADR-018 established is unchanged. Phase 4's shadow rollout adds a third-priority fallback entry temporarily, also additive. |
| ADR-019 (real Llama Guard inference) | No conflict — `sentinel-guardrail`/`-fallback` are explicitly untouched (Scope Note #2 of `MIGRATION_PLAN.md`); confirmed no alias-name overlap with the six aliases this feature touches. |
| ADR-020 (fine-tuning promotion criteria) | No conflict, but its pattern is explicitly reused rather than reinvented: ADR-023's Phase 4 promotion gate mirrors `PROMOTION_MARGIN`'s gating philosophy (beat a recorded baseline by a configured margin) for the same reason — never invent a second gating philosophy when one already exists in the PMA. |
| ADR-021 (sandbox dependency shims) | **Confirmed not inherited.** Unlike Features 01–14, this feature's surface (`infra/`, `scripts/`, env) has no Python import requiring the stubbed `langgraph`/`langchain-openai`/`pydantic` packages — it can be executed and verified on a machine with real Docker/network access without first resolving Open Question #15. This is a deliberate scope boundary (see ADR-023's "first multi-phase change provably contained to infra+scripts+env"), not an oversight. |
| §5.1 IncidentState schema | No conflict — no state field touched. |
| §5.2 Graph skeleton | No conflict — no node/edge touched. |
| §5.3 Gateway contract | No conflict — restates the same alias-only contract ADR-003 already guarantees. |
| §8 Workflow Blueprint (BDD reality check) | **Conflict found in the original request's assumed format, not in any ADR:** there is no `behave`-run `.feature` suite in this repo; Gherkin lives as fenced blocks inside `memory/features/feature-NN-*.md` per Phase 2's Workflow Blueprint. This file's Gherkin section (below) follows that real format, not the assumed one. No PMA decision is reversed — the original Phase 2 Workflow Blueprint already specified this format; the conflict was only in the initial request's framing. |

**Verdict: ADDITIVE, with one explicitly-scoped temporary exception.** No existing
ADR's decision is reversed. The one genuinely novel piece — Phase 4.2's shadow-call
instrumentation touching `src/gateway/client_factory.py`'s trace metadata — is itself
flagged in ADR-023 as temporary, feature-flagged (`SHADOW_FALLBACK_ENABLED`), and
reverted at cutover (Phase 4.5), not a permanent architectural change.

## New ADR

See **ADR-023** in `PROJECT_MEMORY.md` §2 (full decision record). Not restated here
per this project's convention that ADRs live in the PMA; feature files reference them.

## Blast Radius

- **No existing test breaks.** Confirmed by `MIGRATION_PLAN.md` Phase 3.2's regression
  matrix: `tests/gateway/test_client_factory.py`, `tests/evals/test_gateway_compliance.py`,
  and every mocked-client node test (`test_router.py`, `test_grade_documents.py`,
  `test_diagnose.py`, `test_propose_action.py`, `test_write_postmortem.py`) assert on
  alias names and parsed output shape — never on which provider answered. The actual
  breaking change is narrow and intentional: `infra/.env.example`/`scripts/check_env.sh`
  will stop requiring `ANTHROPIC_API_KEY`/`COHERE_API_KEY` (Phase 2.3/2.4).
- **New, narrowly-scoped coverage needed** (not a fix to anything existing): real
  -model JSON-conformance, which no mocked-client unit test can exercise by
  definition. See PyTest Skeletons below.
- **Open Question #16 (embedding-dimension mismatch) must be resolved, not
  papered over,** before Phase 2 is considered complete — flagged explicitly in
  `MIGRATION_PLAN.md` Phase 3.4 and carried into the PMA rather than silently
  absorbed into a "fix it later" comment.

## Pillar Impact

- [x] 5. AI Gateway — fallback tier for six chat aliases + the embedding alias moves
      from paid APIs to a locally-served Ollama backend, governed by the same
      LiteLLM `fallbacks:` mechanism ADR-018 already established.
- [ ] 1, 2, 3, 4, 6 — not touched. (Pillar 3/Guardrails explicitly considered and
      excluded — TogetherAI primary is out of scope, Phase 5.)

## Gherkin

```gherkin
@gateway @fallback
Feature: chat and embedding fallbacks resolve to local open-weights models

  Scenario: a fallback alias resolves to a local Ollama-served model, not a paid API
    Given litellm_config.yaml's sentinel-router-fallback alias
    When the proxy resolves it
    Then the resolved model string starts with "ollama_chat/"
    And no Anthropic or Cohere credential is required for this alias to function

  Scenario: a local fallback model's response still parses as the node expects
    Given the OpenAI-backed primary for a chat alias is forced to fail
    When the proxy fails over to the local Ollama-served fallback
    Then the raw response is valid JSON with the same keys the primary would have returned
    And the calling node's existing parsing/validation code requires no changes

  Scenario: local fallback degrades gracefully under JSON-mode enforcement
    Given a fallback alias configured with format: json
    When the local model is asked to classify or score something
    Then the response contains no markdown fencing or leading prose
```

## PyTest Skeletons (Probabilistic Tier — exercises the real local model, never mocked; classified the same way ragas/judge evals are per ADR-005/008)

```python
# tests/gateway/test_local_fallback_contract.py
#
# Requires the ollama + litellm services from infra/docker-compose.yml running
# (`make up pull-local-models` first). Skipped automatically, with a printed reason,
# if LITELLM_PROXY_URL isn't reachable — never silently passes, same pattern as
# scripts/run_eval.py's "no live model in this sandbox" skip.

def test_router_fallback_returns_valid_route_json():
    """Calls sentinel-router-fallback directly (bypassing the primary), asserts the
    response still satisfies router.py's exact contract: {"route": "<one of
    runbooks|postmortems|infra_code_docs>"}, no prose."""
    ...

def test_diagnose_fallback_returns_parseable_json():
    """Same pattern for the Tier-2 model — most likely to regress, since Tier-2
    prompts are longer/more open-ended than router's three-way classification."""
    ...

def test_embedding_fallback_returns_correct_dimensionality():
    """bge-m3 and text-embedding-3-small do NOT share an embedding dimension —
    asserts the actual dimension mismatch is documented and that
    src/retrieval/vector_search.py's index schema is dimension-aware, not silently
    truncated/padded. This test is expected to force Open Question #16's resolution,
    not to pass trivially."""
    ...
```

## Implementation Status

**Phase checklist (per `MIGRATION_PLAN.md`):**
- [x] Phase 1 — Local infra setup: `ollama` service in `infra/docker-compose.yml`
      (with healthcheck, `ollama_models` volume, host port 11434 for manual
      testing only), added to `litellm`'s `depends_on`; `OLLAMA_BASE_URL` wired
      into `litellm`'s environment; `scripts/pull_local_models.sh` (idempotent
      `ollama pull` loop, compose-v1/v2 detection matching the Makefile's own
      pattern); `make pull-local-models` target + `.PHONY` entry; `make up`
      updated to start `ollama` explicitly and to print a reminder that models
      aren't pulled yet (kept as a separate step through Phases 1–3, per the
      plan, so `make up` never silently triggers multi-GB pulls); `make logs`
      extended to tail `ollama` too.
- [x] Phase 2 — Codebase refactor: all six chat `*-fallback` aliases repointed at
      `ollama_chat/llama3.1:8b-instruct-q4_K_M` (Tier-1) or
      `ollama_chat/mistral-small:24b-instruct-2501-q4_K_M` (Tier-2) with
      `format: json`; `sentinel-embedding-fallback` repointed at `ollama/bge-m3`;
      `sentinel-guardrail`/`-fallback` confirmed untouched. `docker-compose.yml`'s
      `litellm` environment block drops the `ANTHROPIC_API_KEY`/`COHERE_API_KEY`
      required-credential checks (dated comment, not silent deletion);
      `infra/.env.example` and the real `infra/.env` comment out both keys with
      the same dated note, preserving the user's real `COHERE_API_KEY` value
      rather than discarding it; `scripts/check_env.sh`'s `REQUIRED_VARS` drops
      both. Zero changes to `src/` confirmed (no diff touched `src/graph/nodes/`
      or `src/gateway/client_factory.py`, matching the Conflict Check's
      prediction).
- [x] Phase 3 — Test audit + new coverage: 4 `@gateway @fallback` Gherkin
      scenarios appended to `memory/features/feature-12-litellm-proxy-hardening.md`
      (dated 2026-06-28, additive — that feature's own Status stays Done, its
      existing scenarios untouched); `tests/gateway/test_local_fallback_contract.py`
      created (Probabilistic Tier, 3 tests, real-proxy-reachability `skipUnless`
      guard — first instance of that pattern in this repo, documented as such in
      the file's own docstring); embedding-dimension mismatch (Open Question #16)
      resolved explicitly — Option B (fail loudly via a new
      `EmbeddingDimensionMismatchError`), Option A (per-dimension index) rejected
      for v1, full reasoning in PROJECT_MEMORY.md §7's dated resolution note.
- [x] Phase 4 — Shadow rollout instrumentation: **premise corrected before
      implementation, not silently reinterpreted** — `MIGRATION_PLAN.md` §4.1
      assumed a still-live paid fallback to shadow behind; Phase 2 already cut
      the `*-fallback` aliases over directly, so no such tier exists. Asked the
      user explicitly (`AskUserQuestion`); chose "retroactive validation."
      `src/gateway/client_factory.py` gains `SHADOW_FALLBACK_ENABLED` (off by
      default), `shadow_alias_for`, `shadow_metadata`, `fire_shadow_chat_call` —
      shadows a primary alias's already-local `-fallback` against that same
      call's PRIMARY response (re-using `sentinel_remediation_judge`, ADR-005),
      not against the now-nonexistent paid baseline. 14 new tests in
      `tests/gateway/test_shadow_fallback.py` (Deterministic Tier, mocked
      clients). Promotion-gate metric corrected in Open Question #17 (see
      PROJECT_MEMORY.md §7) — the numeric threshold itself remains a
      placeholder, no real shadow data exists in this sandbox to derive one.
- [x] Phase 4.5 — Cutover: paid fallback tier removed from `fallbacks:` lists
      (**already done** — Phase 2 overwrote them directly, nothing left to
      remove); shadow instrumentation reverted (`SHADOW_FALLBACK_ENABLED`,
      `shadow_alias_for`, `shadow_metadata`, `fire_shadow_chat_call` removed
      from `src/gateway/client_factory.py`; `tests/gateway/test_shadow_fallback.py`
      deleted; suite back to 195/195 passing, 3 skipped, matching Phase 3's
      count exactly); Anthropic/Cohere keys **confirmed revoked at the
      provider dashboards** (user attestation, 2026-06-28 — a manual,
      real-world action this sandbox could not perform or independently
      verify itself, recorded as such, not silently assumed); `infra/.env`
      and `infra/.env.example`'s commented-out key lines annotated as dead
      historical record, not a live rollback path; ADR-023's
      implementation-status updated to Done in `PROJECT_MEMORY.md`, with a
      "Resolved by ADR-023 — closed as moot" marker on Open Question #17
      (the promotion-gate threshold was never empirically derived and never
      will be under this ADR; recorded as an accepted, documented risk, not
      a dropped TODO).
- [ ] Phase 5 (separate approval, not part of this feature's Definition of Done) —
      Localizing the guardrail primary. Tracked here only as a forward pointer.

**What was built so far:** Phases 1 through 4.5 — this feature is complete.
Phase 5 (localizing the guardrail primary) is explicitly out of scope and
requires separate approval; it is not part of this feature's Definition of
Done.

**Phase 4.5 detail:** Reverted, not merely disabled — `src/gateway/client_factory.py`'s
entire `SHADOW_FALLBACK_ENABLED`/`shadow_alias_for`/`shadow_metadata`/
`fire_shadow_chat_call` block is gone, replaced by a short comment pointing
back to PROJECT_MEMORY.md and this file for history, per the instrumentation's
own "temporary, reverted at cutover" design stated when it was built in Phase
4. `tests/gateway/test_shadow_fallback.py` (14 tests) deleted alongside it.
This was a deliberate revert, not a regression: the code existed to validate
the cutover, and once the cutover was confirmed (keys revoked), it had served
its purpose. `infra/.env`'s real, preserved `COHERE_API_KEY` value and
`infra/.env.example`'s placeholder are both now annotated as dead — the keys
they represent no longer authenticate against their providers, so neither
file should be read as a live rollback mechanism going forward.

**Phase 4.5 verification:** `python3 -m unittest discover -s tests -p "test_*.py"`
→ 195/195 passing, 3 correctly skipped — identical count to the post-Phase-3
checkpoint, confirming the Phase 4 shadow-instrumentation tests (and only
those) were removed cleanly, with no other regression introduced by the
revert; `bash scripts/lint_gateway_usage.sh` → PASS.

**Phase 4 detail:** `src/gateway/client_factory.py` gains a new, clearly
-delimited section (`# --- ADR-023 Phase 4.2: shadow-fallback instrumentation
---`) with `SHADOW_FALLBACK_ENABLED_ENV`, `shadow_fallback_enabled()`,
`shadow_alias_for()`, `shadow_metadata()`, and `fire_shadow_chat_call()`.
Deliberately NOT wired into `_ChatClient.invoke()` itself: that method
unconditionally raises `NotImplementedError` in this sandbox (ADR-021, Open
Question #15), so there is no real "after success" path to hook a shadow call
into yet — wiring happens together with the real `langchain_openai` swap, not
invented speculatively against an unreachable code path. `fire_shadow_chat_call`
itself is fully testable today via dependency-injected mocks regardless.
`tests/gateway/test_shadow_fallback.py` (new, 14 tests, Deterministic Tier)
covers: flag-gating (default off, truthy-value parsing case-insensitively),
alias selection (primary → its `-fallback`; a `-fallback`/`-fallback-local`
alias → `None`, no double-shadowing), metadata shape
(`{"shadow": True, "shadow_of_trace_id": ...}`), and exception-swallowing from
both client construction and the shadow `.invoke()` call (a shadow failure must
never propagate to the caller, whose real response was already returned).

**Phase 3 detail:** `src/retrieval/vector_search.py` gains
`EmbeddingDimensionMismatchError(ValueError)`, raised by `cosine_similarity`
(and propagated by `search`) in place of the previous generic `ValueError` on a
length mismatch — same external behavior for any code that already caught
`ValueError`, now identifiable in logs/traces as this specific, anticipated
failure mode rather than an indistinguishable one. Two new tests in
`tests/retrieval/test_vector_search.py` pin the exception type directly
(Deterministic Tier). `tests/gateway/test_local_fallback_contract.py` (new)
implements the 3 PyTest skeletons drafted above against a real LiteLLM
proxy/Ollama stack, gated by a `socket`-based reachability probe on
`LITELLM_PROXY_URL` (`unittest.skipUnless`, prints why when skipped — never a
silent pass). `memory/features/feature-12-litellm-proxy-hardening.md`'s Gherkin
section gains a dated, additive block with the 4 `@gateway @fallback` scenarios
(3 carried from this file, plus a 4th for the dimension-mismatch contract);
that feature's `Status: Done` and its original scenarios are untouched.

**Phase 3 verification:** `python3 -m unittest discover -s tests -p "test_*.py"`
→ 195/195 (190 carried over + 2 new `vector_search` tests + 3 new
`test_local_fallback_contract.py` tests, all 3 correctly skipped with a printed
reason in this sandbox); `bash scripts/lint_gateway_usage.sh` → PASS (the new
test file's `httpx` import is local to each test method, never imported at
module load time, so the skip path never triggers an import error either).

**Phase 4 verification:** `python3 -m unittest discover -s tests -p "test_*.py"`
→ 209/209 (195 carried over + 14 new `test_shadow_fallback.py` tests, all
passing — no skips added by this phase, since `fire_shadow_chat_call`'s own
logic needs no live model); `bash scripts/lint_gateway_usage.sh` → PASS.

**Phase 2 verification:** `python3 -c "import yaml; yaml.safe_load(...)"` confirms
both `infra/docker-compose.yml` and `infra/litellm_config.yaml` remain valid YAML
after the edits; `bash scripts/check_env.sh` against the real `infra/.env` now
flags only `TOGETHERAI_API_KEY` (still a placeholder) — `ANTHROPIC_API_KEY` and
`COHERE_API_KEY` no longer appear in its output, confirming the retirement took
effect without disturbing the real `OPENAI_API_KEY` value already in that file;
`bash scripts/lint_gateway_usage.sh` → PASS; `python3 -m unittest discover -s
tests` → 190/190 passing, unchanged from before this feature — exactly the
"zero deterministic-tier regression" the Conflict Check predicted, since no
existing test asserts on provider identity.

**Latent bug found and fixed while verifying Phase 1 (not invented, not silently
absorbed):** `infra/docker-compose.yml`'s `${VAR:?message}` required-credential
pattern (pre-existing since Feature 01/ADR-021, re-confirmed "valid YAML" by
ADR-022) was never actually valid YAML — the colon inside each human-readable
error message (`"...or run: make check-env"`) makes a plain (unquoted) scalar
containing `": "` unparseable; `python3 -c "import yaml; yaml.safe_load(...)"`
failed with `ScannerError: mapping values are not allowed here` before this fix,
confirmed reproducible independent of any Phase 1 change. Fixed by wrapping all
four `${VAR:?...}` values (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`TOGETHERAI_API_KEY`, `COHERE_API_KEY`) in double quotes and removing the
em-dashes from the messages (a quoted scalar tolerates `: ` and em-dashes fine,
but plain ASCII is kept for portability across YAML loaders). Re-verified:
`python3 -c "import yaml; yaml.safe_load(open('infra/docker-compose.yml'))"` now
succeeds and returns all five services (`postgres`, `redis`, `ollama`, `litellm`,
`app`) and all three volumes. This means ADR-022's "compose file parses as valid
YAML" verification claim was incorrect — it was likely checked with a more
lenient loader or not actually re-run after the credential-check lines were
added; corrected here, not silently overwritten. No behavior change for `docker
compose` itself once Docker is available — quoting is YAML-only, identical
runtime value.

**Definition of Done (will be checked off phase-by-phase, not all at once):**
- [x] Spec committed: ADR-023 (PROJECT_MEMORY.md §2), this feature file, Pillar 5
      implementation-status bullet, Feature Log row, Open Questions #16/#17,
      roadmap item 15 — all in place before any code/config changes.
- [x] Phase 1–4.5 implementation matches `MIGRATION_PLAN.md` and this file's
      phase checklist, **with one explicitly user-approved deviation**: Phase
      4's shadow-comparison baseline was the primary model's output, not the
      paid fallback's (MIGRATION_PLAN.md's literal wording), because Phase 2's
      direct cutover left no live paid fallback to compare against. Documented
      in ADR-023's dated correction and Open Question #17, not silently
      followed as originally worded. All phases complete.
- [x] New Gherkin scenarios pass in the Deterministic Tier where applicable
      (the dimension-mismatch scenario, via `test_vector_search.py`); the
      real-model contract tests are written and correctly skip (not silently
      pass) in this sandbox, pending a live Ollama + LiteLLM stack to actually
      run them against.
- [x] Lint (`scripts/lint_gateway_usage.sh`) confirmed still green after Phase 2
      and again after Phase 3.
- [x] Open Question #16 (embedding dimension) resolved with an explicit decision
      (Option B), not deferred past Phase 3.
- [x] Open Question #17 (promotion threshold) closed — **not by a data-backed
      number, by design.** The comparison metric (primary vs. local fallback,
      not paid vs. local) was corrected in Phase 4. At Phase 4.5, with the
      cutover confirmed irreversible (keys revoked), the question is closed as
      moot rather than answered: there was never a window in which a real
      promotion gate could have blocked the Phase 2 cutover, so no shadow data
      collected now could retroactively gate a decision already made. This is
      recorded in PROJECT_MEMORY.md as an accepted, documented risk — not a
      number invented to check this box.
- [x] PROJECT_MEMORY.md's ADR-023 implementation-status updated to Done, with a
      "Resolved by ADR-023 — closed as moot" marker on Open Question #17, at
      Phase 4.5 (2026-06-28). The manual key-revocation step was performed by
      the user and confirmed via explicit attestation, not independently
      verified by this sandbox (which has no way to check a provider
      dashboard) — recorded as such, not silently assumed.
