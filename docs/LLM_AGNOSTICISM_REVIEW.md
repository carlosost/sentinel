# LLM Agnosticism — Diagnosis & Plan

**Date:** 2026-06-28
**Question asked:** How agnostic from specific LLMs is Sentinel? How hard is it to swap one LLM for another, or swap a cloud model for a local one?
**Method:** Direct inspection of `src/gateway/`, `infra/litellm_config.yaml`, every `src/graph/nodes/*.py` call site, `src/reranking/cross_encoder.py`, `src/embeddings/finetuned_embeddings.py`, `scripts/check_env.sh`, `infra/docker-compose.yml`, and the real historical evidence of `ADR-023`/`memory/features/feature-15-local-fallback-migration.md` (a swap this project already executed once, for real).

---

## 1. Diagnosis

### 1.1 The core design is already model-agnostic, and there's real evidence it works

Every chat and embedding call in the codebase goes through exactly one path:
`client_factory.get_chat_client(model="sentinel-<alias>")` /
`get_embedding_client(model="sentinel-<alias>")` (ADR-003). No node, eval script,
or guardrail check ever references a provider name — confirmed by grep across
`src/graph/nodes/*.py` and `src/evals/`. `scripts/lint_gateway_usage.sh` enforces
this in CI by rejecting any direct `openai`/`anthropic` import or client
construction outside `src/gateway/`.

The alias itself is just a label. What it actually resolves to — provider,
model, fallback chain — lives entirely in `infra/litellm_config.yaml`'s
`model_list`. This is the single layer that knows "sentinel-router means
`openai/gpt-4o-mini`, with a fallback to `ollama_chat/llama3.1:8b-instruct`."
LiteLLM's proxy normalizes every provider (OpenAI, Anthropic, TogetherAI,
Ollama, etc.) to the same OpenAI-compatible chat-completions wire format, so
`client_factory` itself never needs provider-specific branching — the
abstraction is structural, not just a convention someone has to remember.

**This already happened once, for real, not hypothetically.** ADR-023/Feature
15 swapped the fallback tier of six chat aliases and the embedding alias from
paid Anthropic/Cohere models to locally-served Ollama models. Its own Conflict
Check (in `feature-15-local-fallback-migration.md`) states the result
explicitly: *"because every node calls models only via
`client_factory.get_chat_client(alias)`, swapping what an alias resolves to in
`litellm_config.yaml` requires zero node changes."* The blast-radius section
confirms no existing node test broke — only `infra/.env.example` and
`scripts/check_env.sh` needed edits, because two credentials (`ANTHROPIC_API_KEY`,
`COHERE_API_KEY`) stopped being required.

**Net: swapping the model behind an existing alias — cloud-to-cloud or
cloud-to-local — is a YAML edit plus an environment-variable edit. Zero
Python changes, zero node changes, zero test changes**, provided the new
model's output still satisfies the alias's existing contract (see 1.3).

### 1.2 Prompting itself doesn't lock you into one vendor's API shape

Checked every node that calls a chat alias (`router`, `grade_documents`,
`diagnose`, `propose_action`, `write_postmortem`): all six parse the model's
output with plain `json.loads(raw_response)` after a "respond with strict
JSON only, no prose" instruction in the prompt text. None uses OpenAI-specific
structured-output mechanisms (`response_format`, `tool_calls`, `bind_tools`,
`with_structured_output`). That's a second point in favor of portability — the
contract between Sentinel and a model is "return parseable JSON," not "support
OpenAI's function-calling API," so almost any chat model can fill an alias.

### 1.3 Two real, found-during-this-review gaps in that agnosticism

**Gap A — JSON reliability isn't pinned at the config layer for every alias,
only for the Ollama fallbacks.** `infra/litellm_config.yaml`'s Ollama
`*-fallback` entries set `format: json`, Ollama's grammar-constrained JSON
mode — a structural guarantee, not just a prompt request. The OpenAI-served
primaries (`sentinel-router`, `sentinel-diagnose`, etc.) have no equivalent
(`response_format: {"type": "json_object"}` in `litellm_params`, which LiteLLM
passes straight through to OpenAI) — they rely on the prompt's "JSON only"
instruction alone. This is asymmetric: the harder-to-trust fallback path is
the one with the structural safety net; the path used 99% of the time isn't.
It also means: if you swap a primary alias to a model whose JSON-following
discipline is worse than GPT-4o's (a plausible cloud-to-cloud or cloud-to-local
swap), nothing in the config layer would catch the resulting increase in
`DiagnoseError`/`RouterError`/etc. — you'd find out from a spike in node
failures, not from a single line of executable config.

**Gap B — two model surfaces sit outside the gateway entirely, by design, and
are not alias-swappable today.** ADR-011 deliberately put the reranker
(`src/reranking/cross_encoder.py`, hardcoded to `BAAI/bge-reranker-base` as a
default argument) and the fine-tuned embedding model
(`src/embeddings/finetuned_embeddings.py`, hardcoded `DEFAULT_MODEL_PATH =
"models/finetuned-embeddings/v1"`) outside `client_factory`/LiteLLM — a
deliberate, documented "local, non-gateway model" precedent (confirmed a third
time at ADR-020), not an oversight. The tradeoff is real and was made
consciously: these are local, in-process models with no remote-call cost or
proxy benefit to capture. But it means: swapping the reranker for a different
cross-encoder, or for a cloud reranking API (e.g., Cohere Rerank, a real
alternative), is a Python code change in `cross_encoder.py`, not a config
edit — the one place in the model stack where "swap the model" and "change
the code" are still the same action. `EMBEDDING_MODEL_VARIANT=base|finetuned`
already exists as a config-driven *choice between two known options*
(`retriever`), but neither option's underlying model name is parameterized
beyond that binary switch.

**A third thing worth naming, not a gap so much as an inherent cost:**
swapping the *embedding* model behind `sentinel-embedding` (not just its
fallback) changes the vector dimensionality the whole corpus was ingested
with. `src/retrieval/vector_search.py`'s `EmbeddingDimensionMismatchError` is
the already-correct, deliberate fail-loud behavior for this (Open Question
#16's resolution) — but it means an embedding-model swap is not "edit one YAML
line," it's "edit one YAML line, then re-run `scripts/ingest_corpora.py`
against every corpus." That's an operational step, not a code gap, but it's
asymmetric with chat-alias swaps and worth being explicit about so nobody is
surprised by stale-dimension search results after a careless swap.

### 1.4 Operational (non-code) coupling to specific providers

`scripts/check_env.sh`'s `REQUIRED_VARS` (`OPENAI_API_KEY`,
`TOGETHERAI_API_KEY`) and `infra/docker-compose.yml`'s comments are the one
place provider identity is spelled out outside `litellm_config.yaml` itself.
ADR-23's migration had to touch both when it dropped `ANTHROPIC_API_KEY`/
`COHERE_API_KEY`. This is appropriate — a credential check *should* know which
credentials are actually required — but it does mean a swap that changes
*which* provider is required (not just which model, same provider) has three
files to touch in lockstep (`litellm_config.yaml`, `check_env.sh`,
`.env.example`), with nothing today that checks they stay consistent with each
other the way `tests/gateway/test_litellm_config_yaml.py` checks that aliases
in code match aliases in config.

### 1.5 Summary verdict

| Surface | Agnostic today? | Swap cost |
|---|---|---|
| Chat models behind an existing alias (router, grader, diagnose, propose-action, postmortem, judge) | Yes — proven by ADR-023 | Edit `litellm_config.yaml`, edit env if a new provider | 
| Guardrail model | Yes (same mechanism) | Same as above |
| Primary embedding model | Yes, but with an operational cost | Edit YAML + re-ingest every corpus |
| JSON-output reliability across a swap | Partial — relies on prompt text for primaries | No structural enforcement at config layer for OpenAI-served aliases |
| Reranker model | No | Code change in `cross_encoder.py` (deliberate scope, ADR-011) |
| Fine-tuned embedding model | No | Code change in `finetuned_embeddings.py` (deliberate scope, ADR-020) |
| Credential/provider bookkeeping consistency | Manual | Three files, no automated cross-check |

---

## 2. Plan

Five independent, prioritized items. None requires reopening ADR-011/ADR-020's
"reranker/fine-tuned embeddings stay local" decision — that scope boundary is
correct and is left alone. The plan closes the gaps *within* the existing
architecture, in the same Spec-Driven/TDD style as Feature 12/ADR-023.

### Item 1 (highest leverage, do first) — Pin JSON-mode enforcement at the config layer for every primary alias, not just the Ollama fallbacks — **Done, 2026-06-28**

(See `memory/features/feature-12-litellm-proxy-hardening.md`'s dated note for
the full account, including a real correction the new test itself caught
mid-fix: `sentinel-guardrail-fallback`'s `openai/omni-moderation-latest` had
to be excluded from scope, since the `/moderations` endpoint has no
`response_format` concept at all.)

Add `response_format: {"type": "json_object"}` to every OpenAI-served
`litellm_params` entry in `infra/litellm_config.yaml` (the six chat primaries;
not the embedding or guardrail aliases, which don't free-text-JSON). This
closes the asymmetry in Gap A with a one-file, no-code change, and makes the
JSON-output contract enforced by configuration for the path that actually
carries production traffic, matching what the fallback path already has.
**TDD order:** extend `tests/gateway/test_litellm_config_yaml.py` with
`test_every_openai_served_chat_alias_enforces_json_response_format`, confirm
it fails red against the current config, then add the six lines and confirm
green. Document as a dated addendum to `feature-12-litellm-proxy-hardening.md`
(ADR-018's home).

### Item 2 — Add an explicit "swap a model" runbook, generalized beyond ADR-023's one-time use — **Done, 2026-06-28**

(Written as `docs/SWAPPING_MODELS.md`, not a section of an existing file — see
that file directly, and `memory/features/feature-12-litellm-proxy-hardening.md`'s
dated note.)

ADR-023 proved the mechanics work but left the playbook implicit in one
feature file scoped to that specific migration. Write a short, generic,
reusable **`docs/SWAPPING_MODELS.md`** (or a new section in
`feature-12-litellm-proxy-hardening.md`, since it already owns the config
surface) covering: (a) chat/guardrail alias swap = edit `model_list` entry +
`scripts/check_env.sh` + `.env.example` if the provider changes, re-run
`test_litellm_config_yaml.py` + `lint_gateway_usage.sh`; (b) embedding-model
swap = same, plus mandatory corpus re-ingestion via
`scripts/ingest_corpora.py` before any traffic uses the new alias, called out
as a hard prerequisite, not a suggestion; (c) reranker/fine-tuned-embedding
swap = explicitly out of scope for a config-only swap, requires a code change
in the named module, by design (ADR-011/ADR-020). This turns "I read the
gateway code to figure out how to swap a model" into "I follow the runbook,"
which is the actual point of this project's Living Memory convention.

### Item 3 — Add a structural test that keeps `check_env.sh`'s required-credential list honest against `litellm_config.yaml` — **Done, 2026-06-28**

(See `memory/features/feature-12-litellm-proxy-hardening.md`'s dated note —
no existing drift to fix, so teeth were verified by a temporary synthetic
edit + revert rather than a real red-then-green cycle.)

Today, `litellm_config.yaml`'s `model:` provider prefixes (`openai/`,
`ollama_chat/`, `together_ai/`) and `check_env.sh`'s `REQUIRED_VARS` are two
independently hand-maintained lists with no test linking them — the same
"two files that drift" shape `tests/gateway/test_litellm_config_yaml.py`
already fixed once for code-vs-config alias drift (see today's earlier fix to
that same file). Add a small test (new file,
`tests/gateway/test_check_env_credentials_match_config.py`, or a method on the
existing test class) that parses `model_list`'s provider prefixes, maps each
real-traffic prefix (`openai`, `together_ai` — `ollama_chat`/`ollama` need no
key) to its expected env var, and asserts `check_env.sh`'s `REQUIRED_VARS`
contains exactly that set, no more, no less. This is the most leveraged single
test to add, since it would have caught the exact edit ADR-023 had to make by
hand in two separate files, mechanically, the next time it happens.

### Item 4 — Make the reranker and fine-tuned-embedding model names swappable via environment, without crossing the gateway boundary

Not a reversal of ADR-011/ADR-020's "stay local, no gateway" decision — just
removing the one remaining hardcoded default. Change
`get_reranker_model(model_name: str = "BAAI/bge-reranker-base")` and
`get_finetuned_embedding_model(model_path: str = DEFAULT_MODEL_PATH)` to read
an optional env var (`SENTINEL_RERANKER_MODEL`, `SENTINEL_FINETUNED_EMBEDDING_PATH`)
as the default, falling back to today's literal default if unset. This makes
"try a different cross-encoder" a deployment-config change instead of a code
edit, while keeping the actual `.predict()`/`.embed_documents()` call sites
untouched — lowest-risk version of closing Gap B, deferred behind Items 1–3
since it's a "nice to have," not a found defect.

### Item 5 — Document the dimension-mismatch re-ingestion cost explicitly in the embedding alias's config comment, not just in code — **Done, 2026-06-28**

`infra/litellm_config.yaml`'s header comment block already documents a lot of
context per alias group; add one line to the `sentinel-embedding` block
pointing at `EmbeddingDimensionMismatchError`'s docstring and stating the
re-ingestion requirement, so the cost is visible to someone editing the YAML
directly, not only to someone who happens to read `vector_search.py` first.
Cheapest item on this list; bundle with Item 1's edit since both touch the
same file in the same sitting.

### Status: Items 1, 2, 3, and 5 are Done (2026-06-28). Item 4 deferred by explicit choice — not started.

---

## 3. What's *not* in this plan, on purpose

No item proposes moving the reranker or fine-tuned embedding model behind
the LiteLLM gateway — ADR-011/ADR-020 made that call deliberately for local,
in-process models with no remote-call cost to capture, and reopening it isn't
what "more agnostic" requires; it would just be re-litigating a settled,
correctly-scoped decision. No item proposes abandoning the alias-indirection
pattern or LiteLLM itself — it's already doing its job, as ADR-023 proved.
