# MIGRATION_PLAN.md — Eliminate Paid Fallback Models (Anthropic, Cohere) for Local Open-Weights Infrastructure

**Status:** Accepted — promoted to `PROJECT_MEMORY.md` as **ADR-023** (ADR-022 was already taken by the Dockerfile/Makefile decision, Feature 01 follow-on; corrected here, no number collision in the PMA).
**Scope correction from request, see "Scope Note" below before reading further.**

---

## Scope Note (read first)

This plan targets the codebase as it actually exists, not as the request assumed:

1. **No Django.** Sentinel is a pure Python project (LangChain/LangGraph/LiteLLM, stdlib-shimmed per ADR-021 in this sandbox). All steps below are Python/YAML/Docker only.

2. **TogetherAI is not a fallback in this system — it is `sentinel-guardrail`'s *primary* model** (Llama Guard 3-8B, ADR-019). The request's constraint #2 ("primary frontier models remain paid, only fallback routing moves local") therefore excludes TogetherAI from this plan's core scope by the request's own rule. Because Llama Guard 3-8B is itself open-weights and a strong localization candidate, it is carried as **Phase 5 (optional, separate approval)** rather than silently included in Phases 1–4 — swapping a primary is a materially different risk profile than swapping a fallback and deserves its own sign-off.

3. **True scope of Phases 1–4:** `ANTHROPIC_API_KEY` (backs 6 fallback aliases) and `COHERE_API_KEY` (backs 1 embedding fallback alias). These are the only two paid *fallback* dependencies in `infra/litellm_config.yaml`.

4. **Native failover mechanism correction.** The request's constraint #2 asks to prioritize LangChain's `.with_fallbacks()` or LangGraph conditional edges. Neither is compatible with this codebase's existing architecture:
   - **ADR-003** mandates that `src/gateway/client_factory.py` is the *sole* construction path for every model client — nodes never hold a LangChain model object to call `.with_fallbacks()` on.
   - **ADR-006**, enforced by `scripts/lint_gateway_usage.sh` (CI-blocking), greps `src/` and `scripts/` for `ChatOpenAI(`, `ChatAnthropic(`, `OpenAIEmbeddings(`, `import openai`, `import anthropic` and fails the build on a match. Introducing `.with_fallbacks()` at the node level requires constructing exactly those objects outside the gateway — a direct ADR-006 violation.
   - **What is actually "native" here:** failover already exists, today, as LiteLLM's own `fallbacks:` list per model alias in `infra/litellm_config.yaml` (ADR-018). This plan extends that exact mechanism — it does not introduce a second one. Net result: **zero changes to `src/graph/nodes/*.py` or `src/gateway/client_factory.py`.** This is more consistent with "preserve current architecture" than the request's own suggested mechanism would have been.

5. **BDD reality check.** There are no `.feature` files run by `behave` in this repo. Gherkin scenarios live as fenced blocks inside `memory/features/feature-NN-*.md`, paired with PyTest skeletons, per the Phase 2 Development Workflow Blueprint in `PROJECT_MEMORY.md`. Phase 3 below audits that real format, not a `behave` suite that doesn't exist.

6. **Sandbox constraint inherited.** Per ADR-021, this dev environment has no PyPI/Docker egress; `langchain_openai`/`langgraph` are stdlib stand-ins whose `.invoke()` raises `NotImplementedError` by design. This plan is written to be executed on a machine with real network/Docker access (the user's own machine, per Open Question #15) — it cannot be smoke-tested end-to-end inside this sandbox. Every verification step below says explicitly where this matters.

---

## Current State (ground truth, as of this plan)

`infra/litellm_config.yaml` model aliases and what backs them today:

| Alias | Primary | Fallback | Paid dependency removed by this plan |
|---|---|---|---|
| `sentinel-router` / `-fallback` | `openai/gpt-4o-mini` | `anthropic/claude-3-5-haiku-20241022` | ✅ Anthropic |
| `sentinel-grader` / `-fallback` | `openai/gpt-4o-mini` | `anthropic/claude-3-5-haiku-20241022` | ✅ Anthropic |
| `sentinel-diagnose` / `-fallback` | `openai/gpt-4o` | `anthropic/claude-3-5-sonnet-20241022` | ✅ Anthropic |
| `sentinel-propose-action` / `-fallback` | `openai/gpt-4o` | `anthropic/claude-3-5-sonnet-20241022` | ✅ Anthropic |
| `sentinel-postmortem` / `-fallback` | `openai/gpt-4o-mini` | `anthropic/claude-3-5-haiku-20241022` | ✅ Anthropic |
| `sentinel-judge` / `-fallback` | `openai/gpt-4o` | `anthropic/claude-3-5-sonnet-20241022` | ✅ Anthropic |
| `sentinel-embedding` / `-fallback` | `openai/text-embedding-3-small` | `cohere/embed-english-v3.0` | ✅ Cohere |
| `sentinel-guardrail` / `-fallback` | `together_ai/...Llama-Guard-3-8B` | `openai/omni-moderation-latest` | ❌ out of scope — see Scope Note #2 |

Every chat node (`router`, `grade_documents`, `diagnose`, `propose_action`, `write_postmortem`, the eval judge) calls its model with a "respond with strict JSON only, no prose" instruction and parses the result with `json.loads`, validating shape by hand (e.g. `router.py`'s `RouterError` on an invalid `route`; `guardrails/check.py`'s `GuardrailCheckError`). **There is no Pydantic schema layer to preserve** — ADR-021 stubbed `pydantic` too, and even outside the sandbox constraint this repo never adopted `langchain`'s structured-output/Pydantic parsing pattern. The real conformance risk is narrower and more concrete than "Pydantic compliance": *does the local model reliably return bare JSON matching the same keys, with no markdown fencing or preamble.* Phase 3 treats this as the central regression risk.

---

## Phase 1 — Local Infrastructure Setup & Configuration

**Goal:** stand up local model serving, reachable from the existing `litellm` container by service name, with zero new application-level servers.

### 1.1 Runtime choice: Ollama, not vLLM, as the default

Ollama is chosen over vLLM as the primary runtime:
- Single container, OpenAI-compatible `/v1/chat/completions` and `/v1/embeddings` endpoints out of the box — LiteLLM talks to it via the `ollama_chat/` or `openai/`-compatible provider prefix with zero custom adapter code.
- Native GGUF quantization support (`Q4_K_M` etc.) without a separate conversion/quantization pipeline (vLLM's quantized-serving story requires AWQ/GPTQ pre-quantized checkpoints or its own quant tooling — more moving parts for the same outcome here).
- Matches constraint #1 ("no new runtime servers unless physically necessary") — Ollama is the smallest possible footprint that satisfies an OpenAI-compatible local inference endpoint.

vLLM is named as an explicit **Phase 1 alternative** (1.5 below) for the case where Tier-2 throughput under concurrent fallback load proves Ollama's single-request-queue serving insufficient — do not adopt it by default.

### 1.2 Model selection (two tiers, matching the existing haiku/sonnet split)

| Tier | Replaces | Model | Quantization | Approx. disk/VRAM | Ollama pull |
|---|---|---|---|---|---|
| Tier-1 (light) | `claude-3-5-haiku` fallback slots (`router`, `grader`, `postmortem`) | `llama3.1:8b-instruct` | `Q4_K_M` | ~4.9 GB | `ollama pull llama3.1:8b-instruct-q4_K_M` |
| Tier-2 (heavy reasoning) | `claude-3-5-sonnet` fallback slots (`diagnose`, `propose-action`, `judge`) | `mistral-small:24b-instruct` | `Q4_K_M` | ~14 GB | `ollama pull mistral-small:24b-instruct-2501-q4_K_M` |
| Embedding | `cohere/embed-english-v3.0` | `bge-m3` (BAAI family — same org as the project's existing fine-tune target `bge-small-en-v1.5`, ADR-020) | n/a (already a small dense model) | ~1.2 GB | `ollama pull bge-m3` |

**Open Question (new, to log in `PROJECT_MEMORY.md` §7 on acceptance):** Tier-2's 14 GB footprint assumes the host has at least 16 GB of free RAM/VRAM. This has not been verified against the actual deployment target. If the target machine can't clear that bar, the fallback degrades to **Phi-3-medium-4k-instruct Q4_K_M (~7.9 GB)** as a documented downgrade path — log which one is actually running in the ADR, never assume silently (same convention as Open Questions #8/#12/#13/#14).

### 1.3 Add an `ollama` service to `infra/docker-compose.yml`

```yaml
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_models:/root/.ollama
    # Uncomment if the host has an NVIDIA GPU + nvidia-container-toolkit installed.
    # Falls back to CPU inference otherwise — slower, but functionally correct,
    # which matters for the shadow-rollout comparison in Phase 4.
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1
    #           capabilities: [gpu]
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 10s
      timeout: 5s
      retries: 5
```

Add `ollama_models` to the top-level `volumes:` block, and add `ollama` to `litellm`'s `depends_on:` list (mirrors the existing `redis` dependency).

### 1.4 Model pull automation — `scripts/pull_local_models.sh`

```bash
#!/usr/bin/env bash
# Pulls every model this migration's fallback aliases depend on. Idempotent —
# `ollama pull` no-ops if the model is already present at that tag.
set -euo pipefail

MODELS=(
  "llama3.1:8b-instruct-q4_K_M"
  "mistral-small:24b-instruct-2501-q4_K_M"
  "bge-m3"
)

for m in "${MODELS[@]}"; do
  echo "Pulling $m ..."
  docker compose -f infra/docker-compose.yml exec ollama ollama pull "$m"
done
```

### 1.5 Makefile wiring

Add to `Makefile` (mirrors the existing `check-env` pattern):

```makefile
## pull-local-models  |  Pull every local fallback model into the ollama container
pull-local-models:
	@printf "$(CYAN)$(BOLD)▶ Pulling local fallback models into ollama...$(RESET)\n"
	@bash scripts/pull_local_models.sh
	@printf "$(GREEN)✓ Local models ready.$(RESET)\n"
```

Make `up` depend on it once Phase 4 flips local fallbacks on for real (`up: check-env pull-local-models`) — keep it a separate, explicit step during Phases 1–3 so `make up` doesn't silently start pulling multi-GB models the first time someone runs it.

### 1.6 Expose Ollama to the `litellm` container

`litellm` reaches `ollama` by Docker service DNS — no port-forwarding to the host is required for that link (the `11434:11434` host mapping above is for your own manual testing/`curl` only). Add to `litellm`'s `environment:` block in `infra/docker-compose.yml`:

```yaml
      OLLAMA_BASE_URL: http://ollama:11434
```

### 1.7 Alternative: vLLM (only if Ollama's serial request queue becomes a bottleneck)

If shadow-rollout load testing (Phase 4) shows Ollama's default single-slot generation queue can't keep up with concurrent fallback traffic, swap `ollama` for a `vllm/vllm-openai` container per Tier-2 model, e.g.:

```yaml
  vllm-tier2:
    image: vllm/vllm-openai:latest
    command: ["--model", "mistralai/Mistral-Small-24B-Instruct-2501", "--quantization", "awq", "--port", "8001"]
    ports: ["8001:8001"]
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

This requires an AWQ/GPTQ-quantized checkpoint (not the same GGUF file Ollama uses) — treat this as a separate model-acquisition step, not a drop-in swap, if it's ever exercised.

---

## Phase 2 — Codebase Refactoring & Fallback Integration

**Goal:** point the existing fallback aliases at local models. Per the Scope Note, this is entirely `infra/litellm_config.yaml` + env/Makefile changes — **no file under `src/` changes.**

### 2.1 `infra/litellm_config.yaml` — fallback `litellm_params` swap

Each `*-fallback` model entry gets a new `model:` provider string (LiteLLM's native `ollama_chat/` prefix) and an explicit `api_base` pointing at the Phase 1 service. Before:

```yaml
  - model_name: sentinel-router-fallback
    litellm_params:
      model: anthropic/claude-3-5-haiku-20241022
```

After:

```yaml
  - model_name: sentinel-router-fallback
    litellm_params:
      model: ollama_chat/llama3.1:8b-instruct-q4_K_M
      api_base: os.environ/OLLAMA_BASE_URL
      # Forces Ollama's grammar-constrained JSON mode — this is the single
      # highest-leverage mitigation for the "strict JSON, no prose" contract
      # every node depends on (see Phase 3's conformance risk). Without this,
      # a quantized 8B model is meaningfully more likely than GPT-4o-mini to
      # wrap its answer in markdown fencing or a leading sentence.
      format: json
```

Apply the same pattern to `sentinel-grader-fallback` and `sentinel-postmortem-fallback` (Tier-1 → `llama3.1:8b-instruct-q4_K_M`), and to `sentinel-diagnose-fallback`, `sentinel-propose-action-fallback`, `sentinel-judge-fallback` (Tier-2 → `mistral-small:24b-instruct-2501-q4_K_M`).

`sentinel-embedding-fallback`:

```yaml
  - model_name: sentinel-embedding-fallback
    litellm_params:
      model: ollama/bge-m3
      api_base: os.environ/OLLAMA_BASE_URL
```

`sentinel-guardrail` / `sentinel-guardrail-fallback`: **unchanged** — see Scope Note #2 / Phase 5.

### 2.2 `infra/docker-compose.yml` — `litellm` service environment

Remove the now-unneeded *required* checks for the two retired paid dependencies, since they no longer back anything:

```diff
       REDIS_HOST: redis
       REDIS_PORT: "6379"
       OPENAI_API_KEY: ${OPENAI_API_KEY:?Missing OPENAI_API_KEY — copy infra/.env.example to infra/.env and fill it in, or run: make check-env}
-      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:?Missing ANTHROPIC_API_KEY — copy infra/.env.example to infra/.env and fill it in, or run: make check-env}
       TOGETHERAI_API_KEY: ${TOGETHERAI_API_KEY:?Missing TOGETHERAI_API_KEY — copy infra/.env.example to infra/.env and fill it in, or run: make check-env}
-      COHERE_API_KEY: ${COHERE_API_KEY:?Missing COHERE_API_KEY — copy infra/.env.example to infra/.env and fill it in, or run: make check-env}
+      OLLAMA_BASE_URL: http://ollama:11434
```

(`TOGETHERAI_API_KEY` stays required — it backs the guardrail primary, untouched per Scope Note #2.)

### 2.3 `infra/.env.example` and `infra/.env`

Remove the `ANTHROPIC_API_KEY` and `COHERE_API_KEY` blocks (or comment them out with a one-line note "retired by ADR-023 — replaced by local Ollama fallback, see MIGRATION_PLAN.md"). Do not delete the file's history silently — per this project's documentation convention, a commented-out block with a dated note is preferred over a silent deletion, so a future reader can see *why* a credential that used to be required no longer is.

### 2.4 `scripts/check_env.sh`

Remove `ANTHROPIC_API_KEY` and `COHERE_API_KEY` from `REQUIRED_VARS`/`REQUIRED_DESCR` (lines 37–43 currently). `OPENAI_API_KEY` and `TOGETHERAI_API_KEY` remain required (frontier primaries + guardrail primary, both untouched). No new required var is added for Ollama — it has no API key, by design.

### 2.5 What does **not** change

- `src/gateway/client_factory.py` — confirmed zero diff. It only ever receives an alias name; it has no knowledge of which provider backs that alias today.
- `src/graph/nodes/*.py` — confirmed zero diff. Every node's prompt/parsing logic is provider-agnostic by construction (ADR-003).
- `scripts/lint_gateway_usage.sh` — no behavior change; nothing in this migration touches a pattern it scans for.

---

## Phase 3 — Test Case Audit & Regression Matrix

**Goal:** identify every test and spec that encodes an assumption about the *paid* fallback, and add the minimum new coverage needed to trust the *local* one.

### 3.1 Audit method

Searched for any test or spec that names `anthropic`, `claude`, `cohere`, or a fallback alias literally:

```bash
grep -rn "anthropic\|claude-3-5\|cohere" tests/ memory/features/*.md PROJECT_MEMORY.md
```

### 3.2 Regression matrix

| File | Current assertion | Affected by this migration? | Action |
|---|---|---|---|
| `tests/gateway/test_client_factory.py` | Asserts `get_chat_client`/`get_embedding_client` pass the alias name straight through, never a raw provider string | No — alias names (`sentinel-router-fallback`, etc.) are unchanged, only what they resolve to in `litellm_config.yaml` | None |
| `tests/evals/test_gateway_compliance.py` | Asserts ADR-006 lint passes (no direct provider SDK import) | No — config-only change | None |
| `tests/graph/nodes/test_router.py`, `test_grade_documents.py`, `test_diagnose.py`, `test_propose_action.py`, `test_write_postmortem.py` | Mock `client_factory.get_chat_client(...).invoke` and assert on parsed `route`/`grade`/etc. — never assert *which* provider answered | No — these tests are provider-agnostic by construction, exactly because of ADR-003 | None |
| `memory/features/feature-12-litellm-proxy-hardening.md` Gherkin | Scenarios describe "primary → secondary provider model on error/timeout" generically, no model names asserted | Conceptually relevant — needs a new scenario, not a fix | **Add scenario** (3.3 below) |
| `tests/guardrails/test_check.py` | Mocks `client_factory`, asserts `GuardrailVerdict` shape/cache-eligibility | No — guardrail is out of scope (Scope Note #2) | None |
| `infra/.env.example`, `scripts/check_env.sh` | Hard-require `ANTHROPIC_API_KEY`/`COHERE_API_KEY` | **Yes — this is the actual breaking change** | Already covered, Phase 2.3/2.4 |

**Conclusion:** because every node was already built provider-agnostic (the entire point of ADR-003), this migration's *code-level* regression surface is small. The real risk is **behavioral, not structural**: does the local model's output still parse. That's not something the existing mocked-client unit tests can catch by definition (they never call a real model) — it needs new, narrowly-scoped coverage that explicitly does call the real local endpoint.

### 3.3 New Gherkin scenario — append to `memory/features/feature-12-litellm-proxy-hardening.md`

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

### 3.4 New PyTest coverage — `tests/gateway/test_local_fallback_contract.py`

This is the contract test the migration actually needs — it is intentionally **not** a mocked-client unit test, because the thing being tested is real-model JSON conformance, which a mock can't exercise:

```python
"""
Probabilistic Tier (same classification as ragas/judge evals — ADR-005/008):
exercises the *real* local Ollama-served fallback model, not a mock. Requires
the ollama + litellm services from infra/docker-compose.yml to be running
(`make up pull-local-models` first). Skipped automatically if LITELLM_PROXY_URL
isn't reachable, the same pattern scripts/run_eval.py uses for "no live model in
this sandbox" — never silently passes, prints why it skipped.
"""

import json
import os
import unittest

import requests  # or whatever this repo's eventual real-dependency swap uses


def _proxy_reachable() -> bool:
    base = os.environ.get("LITELLM_PROXY_URL")
    if not base:
        return False
    try:
        requests.get(f"{base}/health", timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(_proxy_reachable(), "LiteLLM proxy not reachable — run `make up` first")
class TestLocalFallbackContract(unittest.TestCase):
    def test_router_fallback_returns_valid_route_json(self):
        """Calls sentinel-router-fallback directly (bypassing the primary) and
        asserts the response still satisfies router.py's exact contract:
        {"route": "<one of runbooks|postmortems|infra_code_docs>"}, no prose."""
        ...

    def test_diagnose_fallback_returns_parseable_json(self):
        """Same pattern for the Tier-2 model — this is the one most likely to
        regress, since Tier-2 prompts are longer/more open-ended than router's
        three-way classification."""
        ...

    def test_embedding_fallback_returns_correct_dimensionality(self):
        """bge-m3 and text-embedding-3-small do NOT share an embedding dimension
        — this is a real, structural incompatibility the migration must not
        paper over. Document the actual dimension mismatch and confirm
        src/retrieval/vector_search.py's index schema is dimension-aware (or
        requires a separate index per embedding model), not a silent
        truncation/padding hack."""
        ...
```

**Flag explicitly, don't silently fix:** the embedding-dimension mismatch in the last test above is a real architectural question this plan surfaces but does not resolve — `text-embedding-3-small` is 1536-dim, `bge-m3` is 1024-dim. If `sentinel-embedding` ever actually fails over to `sentinel-embedding-fallback` against an index built for 1536-dim vectors, that is a hard failure, not a degraded one. Resolving this (separate index per embedding dimension, or a fallback that only logs/alerts rather than serving degraded retrieval) is a decision for the ADR this plan becomes — do not ship Phase 2 without an explicit answer here.

---

## Phase 4 — Shadow Verification Rollout

**Goal:** prove the local fallback is trustworthy under real traffic patterns before any paid key is revoked.

### 4.1 Shadow mode via LiteLLM, not a code change

`infra/litellm_config.yaml` model aliases support multiple fallback entries in priority order. Temporarily list the local model as a *third*-priority fallback, behind both the existing primary and the still-live paid fallback:

```yaml
  - model_name: sentinel-router
    litellm_params:
      model: openai/gpt-4o-mini
      fallbacks: ["sentinel-router-fallback", "sentinel-router-fallback-local"]
  - model_name: sentinel-router-fallback
    litellm_params:
      model: anthropic/claude-3-5-haiku-20241022   # still live, still paid
  - model_name: sentinel-router-fallback-local
    litellm_params:
      model: ollama_chat/llama3.1:8b-instruct-q4_K_M
      api_base: os.environ/OLLAMA_BASE_URL
      format: json
```

This does not yet shadow real primary-success traffic — it only fires when *both* the primary and the paid fallback fail, which will rarely happen. For an actual shadow comparison, add a second, non-blocking call:

### 4.2 Trace-tagged shadow calls

`client_factory._with_trace_metadata` already merges `metadata={"trace_id": ...}` into every gateway call (ADR-018) — extend this, additively, for the duration of the shadow period only, by having the node optionally issue a second, fire-and-forget call to the `-local` alias whenever the primary succeeds, tagged `metadata={"shadow": True, "shadow_of_trace_id": <primary trace id>}`. This is the one place this migration *does* touch `src/` — and only as a temporary, feature-flagged addition (`SHADOW_FALLBACK_ENABLED=true`), removed once Phase 4 concludes. Treat this itself as its own mini-ADR-scoped change, reviewed and reverted explicitly, not left in permanently.

### 4.3 What to compare in LangSmith

For every shadowed call pair, log and compare:
- **JSON validity rate** — did the local model's raw response parse at all (the dominant risk identified in Phase 3).
- **Schema match rate** — same keys, same value types, same enum membership (e.g. `route` ∈ `VALID_ROUTES`).
- **Semantic agreement** — for `diagnose`/`propose_action`/`judge`, run the existing `sentinel_remediation_judge` (ADR-005) a second time, scoring the local output the same way the golden-set judge already scores the primary's output, rather than inventing a new metric.
- **Latency** — local CPU/GPU inference latency under realistic concurrency, the actual evidence needed to decide between Ollama and the Phase 1.7 vLLM fallback.

### 4.4 Promotion gate

Mirror the existing fine-tuning promotion pattern (ADR-020's `PROMOTION_MARGIN` on `ragas context_precision`) rather than inventing a new gating philosophy: define a **local-fallback promotion threshold** — e.g. ≥98% JSON-validity rate and judge-score parity within a configured margin of the paid fallback's historical baseline — before flipping `ANTHROPIC_API_KEY`/`COHERE_API_KEY` from required to removed in `check_env.sh`. The exact numeric threshold is a placeholder until real shadow data exists — log it as a new Open Question in `PROJECT_MEMORY.md` §7, following the same "never assert a number with no empirical basis" convention as Open Questions #8/#12/#13/#14, not a value invented for this plan.

### 4.5 Cutover

Only after Phase 4.4's gate passes:
1. Remove the `-fallback` (paid) tier from each alias's `fallbacks:` list in `litellm_config.yaml`, leaving only `-fallback-local`.
2. Rename `*-fallback-local` → `*-fallback` (so alias names stay stable for any future reader) and delete the old paid entries.
3. Revert the Phase 4.2 shadow-call instrumentation.
4. Revoke the Anthropic and Cohere API keys at the provider dashboards — not just remove them from `.env`.
5. Write the accepted ADR-023 in `PROJECT_MEMORY.md`, following this project's mandatory continuous-documentation convention: context, decision, consequences, status, plus a "Resolved by ADR-023" marker on whichever Open Question this plan's promotion-threshold note above created.

---

## Phase 5 — Optional Follow-On (out of scope, separate approval): Localizing the Guardrail Primary

Llama Guard 3-8B (`sentinel-guardrail`'s primary, currently served via TogetherAI) is open-weights and Ollama-servable today (`ollama pull llama-guard3:8b`). Unlike Phases 1–4, this swaps a **primary**, not a fallback — a different risk class entirely, since it sits on every single request's input/output moderation path with no paid fallback shadow period implied by the original request. If pursued, treat it as its own plan with its own Phase 4-equivalent shadow rollout against `evals/guardrail_redteam.jsonl`'s precision/recall scorer (already built, Feature 13) before touching the primary — do not fold it into ADR-023 above.
