# LiteLLM Usage Review

**Date:** 2026-06-28
**Scope:** How Sentinel uses the LiteLLM Proxy today, and whether that usage is still
correct after ADR-023's local-fallback migration (Feature 15, Phases 1–4.5, now Done).
**Companion reading:** `PROJECT_MEMORY.md` §3 Pillar 5, ADR-003/006/018/023;
`memory/features/feature-12-litellm-proxy-hardening.md`;
`memory/features/feature-15-local-fallback-migration.md`.

---

## 1. How LiteLLM is used

### 1.1 It is the sole gateway, never a direct provider call
ADR-003 establishes the rule and ADR-006 enforces it mechanically:
`src/gateway/client_factory.py` is the only place in the codebase allowed to
construct an LLM or embedding client, and `scripts/lint_gateway_usage.sh` greps
`src/` and `scripts/` for direct `openai`/`anthropic` imports or
`ChatOpenAI(`/`ChatAnthropic(`/`OpenAIEmbeddings(` construction outside
`src/gateway/`, failing CI if it finds any. Every node, the eval judge, and the
guardrail check obtain their client through `get_chat_client(model=...)` or
`get_embedding_client(model=...)` and nothing else.

### 1.2 Alias indirection, not raw provider strings
Callers never name a provider model. They pass a `sentinel-*` alias —
`sentinel-router`, `sentinel-grader`, `sentinel-diagnose`, `sentinel-propose-action`,
`sentinel-postmortem`, `sentinel-judge`, `sentinel-embedding`, `sentinel-guardrail` —
and `infra/litellm_config.yaml`'s `model_list` is the only place that maps an alias
to a real provider model plus its fallback chain. This is why ADR-023's entire
fallback migration touched zero lines in `src/graph/nodes/`: every node was already
provider-agnostic by construction.

### 1.3 Fallback chains
Each primary alias declares one `-fallback` alias via LiteLLM's native `fallbacks:`
list:

| Primary alias | Primary model | Fallback alias | Fallback model |
|---|---|---|---|
| `sentinel-router` | `openai/gpt-4o-mini` | `sentinel-router-fallback` | `ollama_chat/llama3.1:8b-instruct-q4_K_M` |
| `sentinel-grader` | `openai/gpt-4o-mini` | `sentinel-grader-fallback` | `ollama_chat/llama3.1:8b-instruct-q4_K_M` |
| `sentinel-diagnose` | `openai/gpt-4o` | `sentinel-diagnose-fallback` | `ollama_chat/mistral-small:24b-instruct-2501-q4_K_M` |
| `sentinel-propose-action` | `openai/gpt-4o` | `sentinel-propose-action-fallback` | `ollama_chat/mistral-small:24b-instruct-2501-q4_K_M` |
| `sentinel-postmortem` | `openai/gpt-4o-mini` | `sentinel-postmortem-fallback` | `ollama_chat/llama3.1:8b-instruct-q4_K_M` |
| `sentinel-judge` | `openai/gpt-4o` | `sentinel-judge-fallback` | `ollama_chat/mistral-small:24b-instruct-2501-q4_K_M` |
| `sentinel-embedding` | `openai/text-embedding-3-small` | `sentinel-embedding-fallback` | `ollama/bge-m3` |
| `sentinel-guardrail` | `together_ai/meta-llama/Meta-Llama-Guard-3-8B` | `sentinel-guardrail-fallback` | `openai/omni-moderation-latest` |

All chat fallbacks set `format: json` to force Ollama's grammar-constrained JSON
mode — the highest-leverage mitigation for the "strict JSON, no prose" contract
every chat node's parsing code depends on. `sentinel-guardrail`/`-fallback` are
**unchanged** by ADR-023 — explicitly out of scope, deferred to a separate Phase 5
approval.

### 1.4 Production behaviors layered on top (ADR-018)
- **Redis-backed semantic caching**, proxy-wide, `similarity_threshold: 0.95`,
  1-hour TTL — with an explicit eval-determinism carve-out: every eval-harness call
  (`src/evals/evaluator.py::run_judge`) passes `cache={"no-cache": True}`, so eval
  scores never reflect a stale cached response.
- **Three virtual keys** (`sentinel-app`, `sentinel-eval`, `sentinel-dev`), each
  with its own `rpm_limit`/`max_budget`, so a `make eval` run can never starve
  application traffic of rate-limit headroom and vice versa. The numeric caps are
  flagged placeholders (Open Question #12) — not asserted as tuned.
- **`trace_id`-tagged metadata** on every request, merged in by
  `client_factory._with_trace_metadata()`, so the proxy's own cost/usage logs are
  joinable against LangSmith traces (Project Charter success criterion 4).

### 1.5 The sandbox can't run a real LiteLLM proxy
This dev sandbox has no Docker/network egress, so the real `litellm` container
`infra/docker-compose.yml` provisions has never actually been started here.
`src/gateway/litellm_proxy.py::MockLiteLLMProxy` is a stdlib stand-in that loads
the real `infra/litellm_config.yaml` and re-implements the same fallback/cache/
rate-limit *logic* against an injected `provider_call` callable, so the YAML stays
the single source of truth rather than being duplicated into test fixtures. This
is a deliberate, tracked limitation (ADR-021 addendum, Open Question #15) — every
"this works" claim below about cache/fallback/rate-limit *mechanics* is verified
against this simulation, not a live proxy. `_ChatClient.invoke()` and
`_EmbeddingClient.embed_documents()` still unconditionally raise
`NotImplementedError` — no code path in this repo has ever actually completed a
real model call.

### 1.6 ADR-023: local-fallback migration (now Done)
Through Phases 1–4.5, the six chat `*-fallback` aliases and
`sentinel-embedding-fallback` were repointed from paid Anthropic/Cohere models to
locally-served Ollama open-weights models, and the Anthropic/Cohere API keys have
since been revoked at their provider dashboards (user-confirmed 2026-06-28). A
temporary, feature-flagged shadow-validation mechanism added during Phase 4
(`SHADOW_FALLBACK_ENABLED` and friends in `client_factory.py`) has been reverted at
Phase 4.5 per its own "temporary, removed at cutover" design — `client_factory.py`
nets back to its pre-Phase-4 shape, plus `get_chat_client`/`get_embedding_client`
which are unchanged throughout.

---

## 2. Is it being used correctly after the latest changes?

**Short answer: yes, the core gateway pattern is intact and correctly enforced.**
The alias-indirection contract holds everywhere it's supposed to, the lint and the
structural config test both still pass, and the Phase 4.5 revert left no residue —
`client_factory.py` is functionally identical to its pre-ADR-023 state for the two
functions every node actually calls. One real, pre-existing correctness gap
surfaced while reviewing this, described below; it predates ADR-023 and is not a
regression from it, but it is worth fixing.

### 2.1 What's correct
- **Alias indirection is total.** `grep`-confirmed: no file under `src/graph/nodes/`
  references a provider name. Every chat/embedding call site uses a `sentinel-*`
  alias, matching `client_factory.get_chat_client`'s documented contract.
- **The lint still passes** (`scripts/lint_gateway_usage.sh` → PASS) and would catch
  any future direct-SDK-construction regression in `src/` or `scripts/*.py`.
- **`tests/gateway/test_litellm_config_yaml.py` keeps the alias set honest** for the
  surface it scans: every `sentinel-*` alias referenced under `src/*.py` **or
  `scripts/*.sh`** (widened 2026-06-28, see §2.2) is confirmed present in
  `litellm_config.yaml`'s `model_list` with a non-empty `fallbacks` list, and all
  three virtual keys exist with positive limits.
- **The eval-determinism carve-out still holds** — `run_judge` still passes
  `cache={"no-cache": True}`, confirmed by both
  `test_litellm_production_config.py::test_eval_harness_requests_always_set_no_cache`
  and `test_gateway_compliance.py`.
- **The revert was clean.** Removing the Phase 4.2 shadow instrumentation dropped
  the suite from 209 to exactly 195 tests — the same count as the post-Phase-3
  checkpoint, confirming nothing else regressed.
- **The embedding-dimension mismatch is a named, fail-loud contract**
  (`EmbeddingDimensionMismatchError`), not a silent degradation, for the one case
  (`sentinel-embedding-fallback`, 1024-dim `bge-m3`) where a fallback's output shape
  genuinely differs from its primary's (1536-dim `text-embedding-3-small`).
- **Credential hygiene is honest.** `infra/.env`/`.env.example` retired
  `ANTHROPIC_API_KEY`/`COHERE_API_KEY` without deleting the user's real preserved
  value, and both files now say plainly that the keys are revoked and the
  commented-out lines are historical record only, not a working rollback path.

### 2.2 A real gap, found during this review — now fixed (2026-06-28)
`scripts/entrypoint.sh`'s `smoke` mode constructs a client via:

```python
client = get_chat_client(model='sentinel-chat')
```

**`sentinel-chat` does not exist anywhere in `infra/litellm_config.yaml`'s
`model_list`.** It is not one of the eight real aliases. This currently "works"
only because of two facts stacking together:

1. `get_chat_client()` itself never validates the alias against the proxy
   config — it just builds a `_ChatClient` dataclass. Alias resolution only
   happens inside the (currently unreachable) real proxy, or inside
   `MockLiteLLMProxy.complete()`/`fallback_chain()`, neither of which the smoke
   check calls.
2. `tests/gateway/test_litellm_config_yaml.py`'s alias-consistency check only
   scans `*.py` files under `src/` — `scripts/entrypoint.sh` is a shell script
   with an embedded Python heredoc, so it's invisible to that scan, and
   `lint_gateway_usage.sh` checks for direct SDK usage, not alias correctness.

So nothing in CI today would catch this. If `entrypoint.sh`'s smoke check were
ever extended to actually invoke the client (or once Open Question #15's real
`langchain_openai` swap lands and something calls `.invoke()` on it), this would
fail immediately with an unknown-alias error from the real proxy. This is a
latent bug, not a hypothetical one — it just happens to be inert today because
nothing downstream of `get_chat_client()` in the smoke path is reachable yet.

**Fixed, same day.** Took the more durable of the two options: generalized
`test_litellm_config_yaml.py`'s `_aliases_referenced_in_source()` to scan
`scripts/*.sh` alongside `src/*.py`, confirmed the widened scan failed red
against the unfixed `entrypoint.sh` (proving it actually catches this class of
bug), then changed `entrypoint.sh` to `get_chat_client(model='sentinel-router')`
and confirmed green. Full suite (195/195) and `lint_gateway_usage.sh` both
still pass; a sanity grep confirmed no other `scripts/*.sh` file has a similar
embedded alias reference. Full account in
`memory/features/feature-12-litellm-proxy-hardening.md`'s 2026-06-28 dated
note.

### 2.3 Known, already-documented limitations (not new findings)
- **Open Question #15:** no real `langchain_openai`/provider SDK access in this
  sandbox — `_ChatClient.invoke()`/`_EmbeddingClient.embed_documents()` are
  permanently stubbed here, so no test in this repo has ever exercised a real
  network call through LiteLLM. All "correctness" above is verified at the
  config/contract level, not end-to-end.
- **Open Question #12:** the three virtual keys' `rpm_limit`/`max_budget` values
  are still placeholders with no empirical basis.
- **Open Question #17 (closed as moot, ADR-023 Phase 4.5):** the local-fallback
  promotion threshold was never empirically derived, and per the dated correction
  in `PROJECT_MEMORY.md`, never will be under this ADR — the cutover already
  happened in Phase 2 before any gate could apply to it. This is an accepted,
  documented risk, not an oversight.

---

## 3. Bottom line

LiteLLM usage is architecturally sound and the gateway/alias/fallback contract is
correctly enforced by lint + the structural config test, for the surface those
tools actually scan. The Phase 4.5 revert was clean and verified (195/195 tests,
lint PASS, YAML still valid). The one concrete correctness issue is
`entrypoint.sh`'s reference to a nonexistent `sentinel-chat` alias — pre-existing,
currently harmless only because nothing calls `.invoke()` on the client it builds,
and not caught by any existing automated check.
