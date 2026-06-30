# Feature 12 — LiteLLM Proxy Production Hardening

**Phase introduced:** Phase 4
**Status:** Done
**PMA sections touched:** ADR-018 (new), §5.3, §3 Pillar 5, §3 Pillar 4, §7 (new Open
Question), §6 Feature Log, §9 item 12

## Feature Description

Configure the LiteLLM proxy for production behavior: a primary→secondary fallback
chain, Redis-backed semantic caching, and per-API-key rate limits, with cost/usage
logging tagged to LangSmith `trace_id`.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001, ADR-002 | No conflict — no graph/checkpointer surface touched. |
| ADR-003 (Gateway exists) | No conflict — this is the direct fulfillment of the "configured behaviors" ADR-003/Pillar 5 already named but never specified: fallback, caching, rate limits were promised, not designed, until now. |
| ADR-004 (Guardrail stub) | No conflict — Llama Guard is described as "served behind the gateway," but `guardrail_check()` v1 is still a hardcoded stub (no real model call yet per ADR-004/007), so there is no real guardrail model traffic for this feature's config to apply to yet. Noted as a forward dependency for roadmap item 13, not a gap to fix here. |
| ADR-005 (Eval strategy) | **Conflict risk identified, resolved below.** Semantic caching, if applied uniformly, could mask a live model's actual current behavior behind a stale cached response during an eval run — silently undermining ADR-005's requirement that eval scores reflect real model output. Resolved by an explicit cache carve-out (see Decision). |
| ADR-006 (Lint enforcement) | No conflict — proxy config doesn't change client construction paths. |
| ADR-007 (Scaffolding) | No conflict, gap: `docker-compose.yml` provisions a bare `litellm` service but no proxy config file exists yet. Filled additively below. |
| ADR-008 (Eval harness) | No conflict, see ADR-005 row — the eval harness's LLM calls are the specific call site that needs the cache carve-out. |
| ADR-009 through ADR-017 | No conflict — unrelated surfaces (graph nodes, schema fields, HITL, execution). This feature touches infra config only. |
| §5.1 IncidentState schema | No conflict — no field added or changed. |
| §5.2 Graph skeleton | No conflict — confirmed at approval time; this feature adds no node and changes no edge. |
| §5.3 Gateway contract | No conflict — extended with concrete configured behaviors; the existing one-line contract ("every client only via `client_factory.py`") is unaffected, just given substance. |
| §8.2 Deterministic Tier ("Gateway fallback/caching/rate-limit *behavior*") | No conflict — this is the first feature to actually implement the test surface §8.2 already anticipated by name. |

**Verdict: ADDITIVE.** No existing ADR or contract is contradicted; one genuine design
gap (eval-determinism vs. caching) is resolved explicitly rather than left to silently
collide later.

## New ADR

### ADR-018: LiteLLM proxy production configuration — fallback, caching with an eval carve-out, per-key rate limits, trace_id propagation
- **Context:** ADR-003 established that the gateway exists and is the sole chokepoint
  for model calls, and named fallback/caching/rate-limiting as the payoff — but none
  of those behaviors were ever actually configured. Configuring caching naively would
  also create an undetected conflict with ADR-005's eval-determinism requirement.
- **Decision:**
  - **Model aliases & fallback:** `infra/litellm_config.yaml` defines named model
    aliases (e.g. `sentinel-chat`, `sentinel-embedding`) each with a primary provider
    model and one fallback provider model, configured via LiteLLM's native
    `fallbacks` list. `client_factory.get_chat_client(model=...)` and
    `get_embedding_client(model=...)` pass these alias names, not raw provider model
    strings — so fallback chains are swappable in config without touching node code.
  - **Redis-backed semantic caching:** enabled proxy-wide, keyed on
    (alias, prompt-embedding similarity) per LiteLLM's semantic cache feature, default
    TTL applied.
  - **Eval-determinism carve-out (resolves the ADR-005 conflict risk):** every call
    made by the eval harness (`evals/` code, both ragas's internal calls and the
    `sentinel_remediation_judge` evaluator) passes `cache={"no-cache": True}` in its
    LiteLLM request, guaranteeing eval runs always hit a live model. Only
    graph-node traffic (the application path) is eligible for cache hits.
  - **Per-API-key rate limits & cost attribution:** three LiteLLM virtual keys are
    issued — `sentinel-app` (graph nodes, production traffic budget),
    `sentinel-eval` (CI eval harness, separate budget so a `make eval` run can never
    starve application traffic of rate-limit headroom), and `sentinel-dev` (local
    interactive use). Each has its own requests-per-minute and monthly budget cap in
    `litellm_config.yaml`. Specific numeric caps are placeholders pending real usage
    data (new Open Question).
  - **Cost/usage logging tagged to LangSmith `trace_id`:** `client_factory` reads the
    active LangSmith run's trace ID from context and attaches it as
    `metadata={"trace_id": ...}` on every LiteLLM request, so the proxy's own
    cost/usage logs and LangSmith's trace view can be joined on `trace_id` —
    directly implements Project Charter success criterion 4.
- **Consequences:** Fallback/caching/rate-limit specifics are now a fixed contract
  (`infra/litellm_config.yaml`); changing the eval carve-out's mechanism (e.g.,
  removing the `no-cache` override) later is a retrofit against this ADR, not a
  transparent tuning change, since it would silently reintroduce the ADR-005 risk.
- **Status:** Accepted.

## Blast Radius

Additive — no existing ADR superseded, no existing test/spec files broken. This is
the first feature to implement test surface §8.2 had already named in advance
("Gateway fallback/caching/rate-limit behavior"), so no PMA-described expectation is
contradicted, only fulfilled.

**New Open Question flagged:** rate-limit/budget numeric caps for the three virtual
keys are placeholders with no empirical basis — same pattern as ADR-012's relevance
threshold (Open Question #8). Needs revisiting once real usage/cost data exists.

## Pillar Impact

- [x] 5. AI Gateway — fallback chains, semantic caching, per-key rate limits, and
      trace_id-tagged cost logging are now fully specified, closing the gap §3 Pillar
      5's "Implementation status (Feature 01)" note had flagged as deferred to this
      roadmap item.
- [x] 4. LLM Evals — the eval-determinism carve-out (`cache: no-cache` on all eval
      harness calls) is a necessary precondition for ADR-005/008's baseline-comparison
      model to remain valid once caching exists anywhere in the system.
- [ ] 1, 2, 3, 6 — not touched.

## Gherkin

```gherkin
@gateway
Feature: LiteLLM proxy production behaviors

  Scenario: a provider timeout triggers fallback to the secondary model
    Given the primary model for alias "sentinel-chat" is mocked to time out
    When a node calls client_factory.get_chat_client(model="sentinel-chat")
    Then the response comes from the configured fallback model
    And the LangSmith span records the fallback occurred

  Scenario: a repeated application request is served from cache
    Given a graph node makes the same chat request twice in a row
    When the second request is sent
    Then the proxy returns a cached response without re-calling the provider

  Scenario: eval harness calls never hit the cache
    Given the eval harness (ragas or sentinel_remediation_judge) makes a request
      identical to one already cached
    When that request is sent
    Then the request includes cache={"no-cache": true}
    And the provider is called live, not served from cache

  Scenario: the eval virtual key's rate limit is independent of the app key's
    Given sentinel-app's rate limit is exhausted
    When the eval harness makes a request using the sentinel-eval key
    Then the request succeeds, unaffected by sentinel-app's limit

  Scenario: every request is tagged with the active LangSmith trace_id
    Given a node makes a gateway call inside a traced LangSmith run
    When the request reaches the proxy
    Then its metadata includes the run's trace_id
```

**Appended 2026-06-28 (ADR-023, Feature 15, Phase 3) — additive, not a retrofit of
the scenarios above.** The six chat `*-fallback` aliases and the embedding
`-fallback` alias this ADR's fallback mechanism already established now resolve to
local Ollama-served models instead of paid Anthropic/Cohere ones (ADR-023); the
fallback *mechanism* tested above is unchanged, so these scenarios extend this
feature's existing Gherkin rather than belonging in a new feature file. `@gateway
@fallback`-tagged contract tests live in
`tests/gateway/test_local_fallback_contract.py` (Probabilistic Tier — real
Ollama/LiteLLM required, skips with a printed reason otherwise), not alongside this
feature's `MockLiteLLMProxy`-backed Deterministic Tier tests, since they exercise
real local-model output rather than simulated proxy behavior.

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

  Scenario: an embedding-dimension mismatch fails loudly, never silently
    Given the embedding fallback (bge-m3, 1024-dim) answers a query
    And the corpus was ingested with the primary embedding model (1536-dim)
    When the query embedding is compared against corpus rows in vector_search.search
    Then EmbeddingDimensionMismatchError is raised
    And no similarity-ranked result is returned from the mismatched comparison
```

## PyTest Skeletons (all Deterministic Tier — proxy config/behavior contracts, simulated provider failures and mocked cache state; whether fallback/caching changes response *quality* is out of scope, per §8.2's Pillar 5 row: "n/a, gateway behavior is deterministic by design")

```python
# tests/gateway/test_litellm_production_config.py

def test_provider_timeout_triggers_fallback(mock_litellm_proxy):
    """Deterministic Tier."""
    ...

def test_repeated_app_request_is_cache_hit(mock_litellm_proxy):
    """Deterministic Tier."""
    ...

def test_eval_harness_requests_always_set_no_cache(mock_litellm_proxy):
    """Deterministic Tier. Enforces ADR-018's eval-determinism carve-out —
    this is the test that would catch a future regression reintroducing the
    ADR-005 risk."""
    ...

def test_eval_and_app_virtual_keys_have_independent_rate_limits(mock_litellm_proxy):
    """Deterministic Tier."""
    ...

def test_every_gateway_call_carries_trace_id_metadata(mock_litellm_proxy, mock_langsmith_run):
    """Deterministic Tier. Enforces Project Charter success criterion 4."""
    ...
```

## Implementation Status

**What was built:**
- `infra/litellm_config.yaml` — the real config file (not a docstring example):
  `model_list` entries for all 7 aliases actually called in code
  (`sentinel-router`, `sentinel-grader`, `sentinel-diagnose`,
  `sentinel-propose-action`, `sentinel-postmortem`, `sentinel-judge`,
  `sentinel-embedding`), each paired with a `-fallback` alias via LiteLLM's
  native `fallbacks` list, plus a `sentinel-guardrail`/`sentinel-guardrail-fallback`
  pair reserved (commented, not yet called) for Feature 13.
  `litellm_settings.cache: true` with Redis semantic-cache params
  (`similarity_threshold: 0.95`). `general_settings.virtual_keys`: `sentinel-app`,
  `sentinel-eval`, `sentinel-dev`, each with its own placeholder `rpm_limit`/
  `max_budget`/`budget_duration`.
- `src/observability/tracing.py` (new module/package) — `get_current_trace_id()`
  / `traced_run()` over a `contextvars.ContextVar`, the ADR-021-addendum stand-in
  for the real LangSmith SDK's active-run context.
- `src/gateway/litellm_proxy.py` (new) — `MockLiteLLMProxy`: loads the real
  `infra/litellm_config.yaml`, resolves each alias's fallback chain, and
  implements `complete()` against an injected `provider_call` callable with
  fallback-on-exception, an in-memory cache dict honoring a per-call
  `cache={"no-cache": True}` override, independent per-virtual-key in-memory
  rate-limit counters, and a `call_log` recording `metadata` (including
  `trace_id`) for test assertions. This is the Deterministic Tier's stand-in
  for the real networked `litellm` proxy `docker-compose.yml` already
  provisions but this sandbox cannot run.
- `src/gateway/client_factory.py` — `get_chat_client`/`get_embedding_client` now
  merge `metadata={"trace_id": get_current_trace_id()}` into `extra` via a new
  `_with_trace_metadata()` helper, additive to any caller-supplied `metadata`.
- `src/evals/evaluator.py` — `run_judge`'s one real call site now passes
  `cache={"no-cache": True}` (the eval-determinism carve-out).
- `tests/evals/test_gateway_compliance.py` — updated the one assertion that
  pins `run_judge`'s exact `get_chat_client(...)` call to match.
- `tests/gateway/test_litellm_production_config.py` (new) — the 5 pre-drafted
  skeletons, all implemented against `MockLiteLLMProxy`.
- `tests/gateway/test_litellm_config_yaml.py` (new, supplementary) — static
  validation that every `sentinel-*` alias referenced anywhere in `src/` has a
  matching `model_list` entry with a fallback, that all three virtual keys
  exist with positive limits, and that caching is enabled — the structural
  counterpart to the behavioral tests above.
- `tests/observability/test_tracing.py` (new, supplementary) — direct unit
  tests of `traced_run`/`get_current_trace_id`'s context-var contract
  (default-None, set/restore, sequential-run isolation).
- `requirements.txt` — added `pyyaml>=6.0` (used by `litellm_proxy.py` to parse
  the config; confirmed available in this sandbox, unlike most of this
  project's other declared dependencies).

**Deviations from spec:** none structural. The ADR's own prose used
`sentinel-chat`/`sentinel-embedding` as illustrative example aliases; the real
config uses the 7 aliases actually referenced in node code instead (more
useful, and now enforced by `test_litellm_config_yaml.py` so it can't drift
silently in the future).

**New Open Question:** none — the rate-limit/budget-cap placeholder concern
this feature's design phase flagged was already pre-existing as Open Question
#12 in `docs/PROJECT_MEMORY.md` §7 (confirmed by direct read before writing the
Feature Log row, applying the same correction discipline Feature 11's Open
Question #11 mismatch established).

**New ADR-021 addendum:** `src/observability/tracing.py` and
`src/gateway/litellm_proxy.py` are both new sandbox dependency shims (no
PyPI/network egress here for the real `langsmith` SDK or a running `litellm`
proxy) — recorded as an ADR-021 addendum in `docs/PROJECT_MEMORY.md`, growing Open
Question #15's scope.

**Verification:**
- `python3 -m unittest discover -s tests -p "test_*.py"` → 152/152 passing
  (141 carried over from Feature 11 + 11 new).
- `bash scripts/lint_gateway_usage.sh` → PASS.
- `python scripts/run_eval.py` → PASS (harness mechanics only, no quality
  baseline — unchanged caveat from prior features).

**Definition of Done:**
- [x] Spec conflict-checked against every existing ADR/contract.
- [x] New ADR (ADR-018) recorded, `Status: Accepted`.
- [x] Gherkin scenarios match the spec.
- [x] All 5 pre-drafted PyTest skeletons implemented and passing, plus 2
      supplementary test files.
- [x] Implementation matches the spec; no undocumented deviation.
- [x] Full deterministic suite green; lint green; eval harness mechanics green.
- [x] `docs/PROJECT_MEMORY.md` updated (ADR-018 implementation-status bullet,
      ADR-021 addendum, Feature Log row, §9 checkbox). §3 Pillar 4/5
      implementation-status bullets were already accurately pre-drafted —
      confirmed correct on read, no edit needed.
- [x] This file's Status marked Done.

---

**Appended 2026-06-28 (post-ADR-023 Phase 4.5 usage review) — additive, this
feature's `Status: Done` and everything above is untouched.** After Feature 15's
local-fallback migration closed out (ADR-023 Done, shadow instrumentation
reverted), a usage review was run against this feature's own ADR-018 contract to
confirm the LiteLLM gateway is still being used correctly. Full review:
`docs/LITELLM_USAGE_REVIEW.md` (repo root). Summary relevant to this feature:

- The alias-indirection/fallback/caching/rate-limit/trace_id contract this ADR
  established is fully intact. `tests/gateway/test_litellm_config_yaml.py` and
  `tests/gateway/test_litellm_production_config.py` (both owned by this feature)
  still pass unchanged; `scripts/lint_gateway_usage.sh` → PASS.
- The Phase 4.5 revert of Feature 15's temporary shadow instrumentation left
  `src/gateway/client_factory.py`'s `get_chat_client`/`get_embedding_client` —
  the two functions this ADR actually governs — byte-for-byte equivalent to their
  pre-Feature-15 behavior. No drift introduced here by that migration.
- **One pre-existing gap surfaced, not previously documented anywhere:**
  `scripts/entrypoint.sh`'s smoke check calls
  `get_chat_client(model='sentinel-chat')` — `sentinel-chat` is not a real alias in
  `infra/litellm_config.yaml`'s `model_list` (it was this ADR's own illustrative
  example name in its original prose, per the "Deviations from spec" note above,
  but the real config never declared it). This is currently invisible to both this
  feature's `test_litellm_config_yaml.py` (scans `src/*.py` only, not
  `scripts/*.sh`) and to `lint_gateway_usage.sh` (checks for direct SDK usage, not
  alias correctness) — because `get_chat_client()` itself never validates an
  alias against the config; only the real proxy or `MockLiteLLMProxy.complete()`
  would. Harmless today only because nothing in the smoke path calls `.invoke()`.
  Not fixed here — flagged per this project's "surface, don't silently fix"
  convention; full detail and a suggested fix are in `docs/LITELLM_USAGE_REVIEW.md` §2.2.
  Tracked as a candidate new Open Question in `docs/PROJECT_MEMORY.md` if/when picked up.

**Fixed 2026-06-28, same day — closed, not left as a candidate.** Per the
"more durable fix" the review recommended: `_aliases_referenced_in_source()`
in `tests/gateway/test_litellm_config_yaml.py` is generalized from a single
`src/*.py` glob to a list of `(root, glob)` scan targets covering both
`src/*.py` and `scripts/*.sh`, so any future shell-embedded Python referencing
a `sentinel-*` alias is caught by the same mechanism, not a second copy-pasted
scanner. TDD order followed: ran the existing
`test_every_alias_referenced_in_code_is_declared_with_a_fallback` after
widening the scan and confirmed it failed red against the unfixed
`scripts/entrypoint.sh` (`'sentinel-chat' is called in code but missing from
model_list`) before touching `entrypoint.sh` — proving the test catches the
real bug, not just passing trivially. Then fixed `entrypoint.sh`'s smoke check
to `get_chat_client(model='sentinel-router')` (a real alias) and re-ran: green.

**Deviation from the original plan, documented not silently followed:** the
plan called for a new, separate test method
(`test_every_alias_referenced_in_scripts_is_declared_with_a_fallback`).
Implemented instead as a generalization of the *existing* test, since once the
scan helper covers both `src/` and `scripts/`, the existing assertion already
exercises exactly the right thing — a second test would have been a
near-duplicate. The existing test's docstring/module docstring were updated to
say so explicitly, dated.

**Verification:** isolated run of `tests/gateway/test_litellm_config_yaml.py`
→ 3/3 passing (same 3 tests, scan widened, no new test added — see deviation
note); full suite `python3 -m unittest discover -s tests -p "test_*.py"` →
195/195 passing, 3 correctly skipped (same count as before this fix — a
scan-coverage widening + a one-line bug fix, not new test cases);
`bash scripts/lint_gateway_usage.sh` → PASS; sanity grep confirmed no other
`scripts/*.sh` file references a `sentinel-*` alias that the widened scan
would newly trip on (`scripts/check_env.sh`'s `sentinel-*` mentions are inside
a human-readable error string, not a `model=...` call site, so the regex
correctly does not match them).

**Status of the gap:** Resolved. `docs/LITELLM_USAGE_REVIEW.md` §2.2 updated to
point here instead of describing it as open.

---

## 2026-06-28, later same day — docs/LLM_AGNOSTICISM_REVIEW.md Items 1 & 5: pin JSON mode for OpenAI-served primaries; document the embedding swap's re-ingestion cost

A follow-up review of how model-agnostic Sentinel's gateway design actually
is (`docs/LLM_AGNOSTICISM_REVIEW.md`) found Gap A: the Ollama-served fallback tier
gets a structural JSON-output guarantee (`format: json`, Ollama's
grammar-constrained mode), but the OpenAI-served chat primaries — the path
carrying production traffic — had no equivalent and relied on the prompt's
"respond with strict JSON only" instruction alone.

**TDD order followed:** added
`test_every_openai_served_chat_alias_enforces_json_response_format` to
`tests/gateway/test_litellm_config_yaml.py` first, confirmed it failed red
against the unedited config (`'sentinel-router' is served by
'openai/gpt-4o-mini' (OpenAI) but does not pin response_format=json_object`),
then added `response_format: { type: json_object }` to all six OpenAI-served
chat primaries (`sentinel-router`, `sentinel-grader`, `sentinel-diagnose`,
`sentinel-propose-action`, `sentinel-postmortem`, `sentinel-judge`) in
`infra/litellm_config.yaml`.

**A real correction found mid-fix, not silently absorbed:** the test's first
draft excluded only `openai/text-embedding-*` from scope and went red again
against `sentinel-guardrail-fallback` (`openai/omni-moderation-latest`) —
OpenAI's separate `/moderations` endpoint, where `response_format` isn't a
concept at all (it is not a `/chat/completions` model). Adding
`response_format` there would have been an incorrect config edit, not a
missing one. Fixed by excluding `openai/omni-moderation-*` from the test's
scope as well, with the docstring explicitly recording why this exclusion
exists — found by the test itself doing its job, not by manual review.

**Item 5 (bundled, same file, same sitting):** added a dated comment directly
above `sentinel-embedding`'s `model_list` entry stating that swapping its
primary model is not config-only the way the chat aliases are — the new
model's embedding dimensionality must match what `corpora/` was ingested
with, or `EmbeddingDimensionMismatchError`
(`src/retrieval/vector_search.py`, Open Question #16) fires on every
retriever call — and that `scripts/ingest_corpora.py` must be re-run against
every corpus before any traffic uses the new alias. This makes the cost
visible to someone editing the YAML directly, not only to someone who reads
`vector_search.py` first.

**Verification:** isolated run of `tests/gateway/test_litellm_config_yaml.py`
→ 4/4 passing (3 previous + 1 new); full suite
(`python3 -m unittest discover -s tests -p "test_*.py"`) → 196/196 passing, 3
skipped; `bash scripts/lint_gateway_usage.sh` → PASS.

**Status:** Items 1 and 5 of `docs/LLM_AGNOSTICISM_REVIEW.md`'s plan are Done.

---

## 2026-06-28, later still — docs/LLM_AGNOSTICISM_REVIEW.md Item 3: mechanical drift check between check_env.sh and litellm_config.yaml's providers

§1.4 of the agnosticism review named a real, if not-yet-triggered, risk:
`infra/litellm_config.yaml`'s provider prefixes (`openai/`, `together_ai/`,
`ollama_chat/`) and `scripts/check_env.sh`'s `REQUIRED_VARS` are two
independently hand-maintained lists with nothing checking they stay
consistent — the exact shape of drift `test_litellm_config_yaml.py` already
fixed once today for code-vs-config alias names. ADR-023/Feature 15 had to
edit both files by hand, in the same sitting, when it dropped
`ANTHROPIC_API_KEY`/`COHERE_API_KEY` — it worked that time because someone
remembered; nothing would have caught it if they hadn't.

Added new file `tests/gateway/test_check_env_credentials_match_config.py`:
derives the expected required-env-var set from `model_list`'s provider
prefixes via a small, explicit `_PROVIDER_PREFIX_TO_REQUIRED_VAR` map
(`openai` → `OPENAI_API_KEY`, `together_ai` → `TOGETHERAI_API_KEY`;
`ollama`/`ollama_chat` need no key, by omission), parses
`check_env.sh`'s `REQUIRED_VARS=(...)` array with a regex, and asserts the
two sets match exactly in both directions (catches a newly-required
credential nobody added to `check_env.sh`, and a stale one nobody removed).

No existing bug to fix here — today's two files are already consistent, so
this couldn't be driven through a real red-then-green cycle the way Items 1
and 3 (`sentinel-chat`) were. Verified the test actually has teeth instead:
temporarily appended a fake `ANTHROPIC_API_KEY` to `check_env.sh`'s
`REQUIRED_VARS`, confirmed the test failed with the expected
"still requires {'ANTHROPIC_API_KEY'}... no model_list entry... uses that
provider anymore" message, then restored the file from a backup and
confirmed via `diff` that it was byte-for-byte the original before re-running
green.

**Verification:** full suite (`python3 -m unittest discover -s tests -p
"test_*.py"`) → 197/197 passing, 3 skipped (196 + 1 new test); `bash
scripts/lint_gateway_usage.sh` → PASS.

**Status:** Item 3 of `docs/LLM_AGNOSTICISM_REVIEW.md`'s plan is Done.

---

## 2026-06-28, end of day — docs/LLM_AGNOSTICISM_REVIEW.md Item 2: the swap runbook

Wrote `docs/SWAPPING_MODELS.md`, the generalized, reusable version of the
playbook ADR-023/Feature 15 executed once for a specific migration. Written
last among Items 1/3/5/2 on purpose, per the plan's own stated order, so it
describes the *current* state (response_format pinned, the credential-drift
test in place, the embedding re-ingestion comment already in
`litellm_config.yaml`) rather than needing a second pass.

Covers: swapping a chat/guardrail alias's model (config-only, no node
changes — Section 1); swapping the primary embedding model (config plus a
mandatory `make ingest` re-run — Section 2); swapping the reranker or
fine-tuned-embedding model (a real code change, by design, since ADR-011/
ADR-020 deliberately kept both outside the gateway — Section 3); and an
explicit list of what never needs to change for the first two (Section 4,
backed by the lint + structural tests, not just an assertion).

Item 4 (env-configurable reranker/fine-tuned-embedding model names) is
explicitly named as not-yet-done in Section 3, per the user's decision to
leave it for later — the runbook says so rather than silently describing a
capability that doesn't exist yet.

**Status:** Item 2 of `docs/LLM_AGNOSTICISM_REVIEW.md`'s plan is Done. Items 1,
2, 3, and 5 are all Done; Item 4 remains open, deferred by explicit user
choice, not forgotten.
