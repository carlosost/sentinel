# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Primary dev loop — no Docker, no network required
make test-local          # full Deterministic Tier suite via stdlib unittest
python3 -m unittest tests.graph.nodes.test_router   # single test module
python3 -m unittest tests.graph.nodes.test_router.RouterNodeTests.test_router_uses_client_factory  # single test

make lint                # gateway-usage lint (must pass before any merge)

# Docker required
make up                  # start Postgres + Redis + LiteLLM + Ollama
make test                # full pytest suite inside Docker with real deps
make smoke               # one-shot graph build + gateway wiring check
make ingest              # ingest corpora/ into pgvector (fails without live infra)
make pull-local-models   # pull Ollama fallback models (~14 GB, one-time)
make eval                # Probabilistic Tier — ragas + LangSmith judge scores
```

Credentials are required before `make up/smoke/test/shell` — copy `infra/.env.example` to `infra/.env` and fill in `OPENAI_API_KEY`, `TOGETHERAI_API_KEY`, `LITELLM_PROXY_URL`, `LITELLM_VIRTUAL_KEY`, `LANGCHAIN_API_KEY`, and `OLLAMA_BASE_URL`. `make check-env` validates this.

## Architecture

**`docs/PROJECT_MEMORY.md` is the master reference.** Every Architecture Decision Record (ADR) lives there. Read it before making any structural change. Per-feature specs (Conflict Check, Gherkin, PyTest skeletons, Definition of Done) live in `memory/features/feature-NN-*.md`. These are not optional housekeeping — the project's own workflow requires updating both files whenever an ADR or feature changes.

### Graph

`src/graph/build.py` assembles a LangGraph `StateGraph`. All nodes share a single `IncidentState` TypedDict (`src/graph/state.py`). The flow:

```
entry → guardrail_input ─(unsafe)→ reject → END
                        ─(safe)→ router → retriever → reranker → grade_documents
grade_documents ─(low relevance, retries left)→ router          [self-RAG cycle]
               ─(ok)→ diagnose → propose_action → guardrail_output
guardrail_output ─(unsafe)→ reject
                ─(safe, side-effecting)→ await_human_approval   [HITL interrupt]
                ─(safe, read-only)→ execute
await_human_approval ─(approved)→ execute
                     ─(rejected)→ diagnose
execute ─(failure)→ diagnose
       ─(success)→ write_postmortem → guardrail_output → END
```

`src/graph/_compat.py` is a stdlib shim for `langgraph` (ADR-021 — no PyPI egress in the dev sandbox). It supports the full graph including cycles and `interrupt()`/checkpoint resume, but `interrupt()` always raises rather than pausing — the real `PostgresSaver` checkpointer behaviour only works with actual `langgraph`. Replace this shim with a real import once `langgraph` is installable.

### Gateway (ADR-003/006)

**Every LLM and embedding call must go through `src/gateway/client_factory.py`.** The only permitted construction paths are `get_chat_client(model="sentinel-<alias>")` and `get_embedding_client(model="sentinel-<alias>")`. Direct `openai`/`anthropic` imports or SDK client construction outside `src/gateway/` will fail `make lint`.

Model aliases (`sentinel-router`, `sentinel-diagnose`, `sentinel-embedding`, etc.) are defined in `infra/litellm_config.yaml`. Swapping the model behind an alias — including cloud-to-local swaps — is a YAML edit only, zero code change. See `docs/SWAPPING_MODELS.md` for the full runbook. Swapping the primary embedding model additionally requires `make ingest` to re-embed all corpora (dimension mismatch otherwise).

`src/gateway/client_factory.py` currently returns stdlib shim objects (`_ChatClient`/`_EmbeddingClient`) whose `.invoke()`/`.embed_documents()` raise `NotImplementedError` — replace with real `langchain_openai` imports when the environment has PyPI access (Open Question #15 in `docs/PROJECT_MEMORY.md`).

### Test tiers

**Deterministic Tier** (`make test-local`, all tests under `tests/`): fully mocked, no network, no Docker, must pass 100%. Node tests mock `get_chat_client` at the node's own import path: `@patch("src.graph.nodes.router.get_chat_client")`. Gateway contract tests (`tests/gateway/`) use `MockLiteLLMProxy` driven by the real `infra/litellm_config.yaml`.

**Probabilistic Tier** (`make eval`): quality scores (ragas `context_precision`/`faithfulness`, LangSmith LLM-as-judge), gated against versioned thresholds, never asserted with `==`. Lives in `scripts/run_eval.py` and `evals/`.

### Key invariants enforced by tests

- `tests/gateway/test_litellm_config_yaml.py` — every `sentinel-*` alias called in `src/*.py` or `scripts/*.sh` must be declared in `litellm_config.yaml` with a fallback; every OpenAI-served chat alias must set `response_format: {type: json_object}`.
- `tests/gateway/test_check_env_credentials_match_config.py` — `scripts/check_env.sh`'s `REQUIRED_VARS` must exactly match the providers declared in `litellm_config.yaml`'s `model_list`.
- `tests/test_lint_gateway_usage.py` — the lint script itself is tested against synthetic fixture trees.

### Other notable modules

- `src/retrieval/vector_search.py` — raises `EmbeddingDimensionMismatchError` (not caught) on corpus/query dimension mismatch. Deliberate fail-loud design.
- `src/reranking/cross_encoder.py` and `src/embeddings/finetuned_embeddings.py` — local in-process models, intentionally outside the LiteLLM gateway (ADR-011/020).
- `EMBEDDING_MODEL_VARIANT=finetuned` env var — switches `retriever` to use the fine-tuned embedding model instead of `sentinel-embedding`.
- `src/observability/tracing.py` — all gateway calls attach a `trace_id`; `traced_run()` context manager is the entry point.
