# Runbook: Swapping a Model in Sentinel

**Written:** 2026-06-28, as Item 2 of `LLM_AGNOSTICISM_REVIEW.md`'s plan, after
Items 1, 3, and 5 landed — this describes the current state, not an aspiration.
**Audience:** whoever is changing which real model backs a `sentinel-*` alias,
or swapping a cloud provider for a local one (or back).

This is the generalized version of a swap this project has already done once
for real (ADR-023/Feature 15: Anthropic/Cohere fallback → local Ollama). Follow
the relevant section below; each ends with the exact commands to verify nothing
broke.

---

## 1. Swapping a chat or guardrail alias's model (router, grader, diagnose, propose-action, postmortem, judge, guardrail)

This is the cheap case. No application code changes — the alias indirection
(ADR-003) means every node only ever asks for `get_chat_client(model="sentinel-X")`;
nothing downstream of that alias name is hardcoded anywhere in `src/`.

1. Edit the alias's entry in `infra/litellm_config.yaml`'s `model_list` —
   change `litellm_params.model` to the new provider/model string (LiteLLM's
   `provider/model-name` format, e.g. `anthropic/claude-3-5-sonnet-20241022`,
   `ollama_chat/llama3.1:8b-instruct-q4_K_M`).
2. **If the model is OpenAI-served (`openai/...`) and is a chat-completions
   model** (not `omni-moderation-*`), also set
   `response_format: { type: json_object }` on that entry — every node
   parsing this alias's output expects strict JSON
   (`json.loads(raw_response)`), and this pins that contract at the config
   layer instead of relying on the prompt text alone (Item 1, 2026-06-28).
   If the new provider has an equivalent structural JSON-mode flag (Ollama:
   `format: json`; others vary), set that instead/also.
3. **If the new model is served by a provider not already required
   elsewhere in `model_list`**, add its credential to
   `scripts/check_env.sh`'s `REQUIRED_VARS`/`REQUIRED_DESCR` arrays, and add
   a placeholder line to `infra/.env.example` (and a real value to your own
   `infra/.env`, never committed). If you're *removing* the last alias that
   used some provider, remove its credential requirement from both files —
   don't leave it required for nothing (this is exactly the drift Item 3's
   test now catches mechanically; see step 4).
4. Run:
   ```bash
   python3 -m unittest discover -s tests -p "test_*.py"
   bash scripts/lint_gateway_usage.sh
   ```
   `tests/gateway/test_litellm_config_yaml.py` and
   `tests/gateway/test_check_env_credentials_match_config.py` will fail
   loudly and specifically if you missed a fallback, a `response_format`, or
   a credential-list edit — fix what they report before moving on.
5. No node test should need editing. If one does, that's a signal the test
   was asserting on provider identity rather than alias/output-shape — worth
   fixing the test, not papering over it (see `feature-15-local-fallback-migration.md`'s
   Blast Radius section for why this should never happen: every node test
   mocks `get_chat_client` and asserts on the alias name and parsed output
   shape, never on which provider answered).

## 2. Swapping the primary embedding model (`sentinel-embedding`)

Same as Section 1, steps 1–4, **plus one mandatory extra step that has no
equivalent for chat aliases**: the new model's embedding dimensionality must
match what every corpus was ingested with, or `retriever` fails loudly with
`EmbeddingDimensionMismatchError` (`src/retrieval/vector_search.py`, Open
Question #16's deliberate fail-loud resolution — not a bug to "fix" by
catching the exception).

3. **Before any traffic uses the new alias**, re-run:
   ```bash
   make ingest          # or: python3 scripts/ingest_corpora.py
   ```
   against every corpus. There is no partial/incremental path here — every
   row in `InMemoryDocumentStore` was embedded with the old model's
   dimensionality and must be replaced, not appended to.

`infra/litellm_config.yaml` carries a dated comment directly above
`sentinel-embedding`'s entry stating this same requirement, so it's visible
to someone editing the YAML without having read this file or
`vector_search.py` first.

## 3. Swapping the reranker model or the fine-tuned embedding model

**This is not a config change** — these two are deliberately outside the
gateway (ADR-011 for the reranker, ADR-020 for the fine-tuned embedding
model; confirmed a third time as a precedent, not an oversight). They are
local, in-process models with no remote-call cost or proxy benefit (caching,
fallback, rate limiting) to capture, so routing them through LiteLLM was
explicitly rejected for v1. Swapping the actual model requires editing:

- `src/reranking/cross_encoder.py`'s `get_reranker_model(model_name=...)`
  default, or the call site that invokes it, for the reranker.
- `src/embeddings/finetuned_embeddings.py`'s `DEFAULT_MODEL_PATH`/
  `get_finetuned_embedding_model(model_path=...)` default, or the call site,
  for the fine-tuned embedding model.

(`LLM_AGNOSTICISM_REVIEW.md`'s Item 4 — not yet done as of this writing —
would make both of these env-var-configurable without crossing the gateway
boundary, lowering this from "edit Python" to "set an env var." Until that
lands, this is a code change.)

No re-ingestion step applies to a reranker swap (it scores already-retrieved
documents, doesn't change how they were embedded). A fine-tuned-embedding-model
swap *does* need re-ingestion under the `EMBEDDING_MODEL_VARIANT=finetuned`
config path, for the same dimensionality reason as Section 2 — see
`src/finetuning/ab_eval.py`'s promotion-gate docs for how a new finetuned
variant should be validated before being promoted to default.

## 4. What never needs to change for any swap in Sections 1–2

- Any file under `src/graph/nodes/` — confirmed by `scripts/lint_gateway_usage.sh`
  and `tests/gateway/test_litellm_config_yaml.py`'s source scan that no
  provider name ever appears there.
- Prompt templates — they instruct "respond with strict JSON only," never a
  provider-specific structured-output API (`response_format` is set at the
  *config* layer per Section 1 step 2, not by the prompt).
- `src/gateway/client_factory.py` — it only ever sees the alias name; it has
  no per-provider branching to update.

---

## Quick reference

| Swapping... | Code change? | Re-ingestion? | Files to touch |
|---|---|---|---|
| A chat/guardrail alias's model | No | No | `litellm_config.yaml`, maybe `check_env.sh` + `.env.example` |
| The primary embedding model | No | **Yes, mandatory** | Same as above, plus `make ingest` |
| The reranker model | Yes | No | `src/reranking/cross_encoder.py` |
| The fine-tuned embedding model | Yes | Yes, if promoted to default | `src/embeddings/finetuned_embeddings.py` |

Full diagnosis and the rest of the plan this runbook is part of:
`LLM_AGNOSTICISM_REVIEW.md`. The real precedent this runbook generalizes from:
`memory/features/feature-15-local-fallback-migration.md` (ADR-023).
