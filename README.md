# Sentinel — Autonomous SRE Incident Copilot

Sentinel is a learning project for building a production-grade LLM application from
scratch with LangGraph, LangSmith, LangChain, and Advanced RAG — built under a strict
Spec-Driven Development → BDD → TDD workflow. **All 14 Phase 4 roadmap items are
implemented and tested** (207/207 tests passing), all stdlib shims have been replaced
with real packages via conditional imports (ADR-024), and the system ships a FastAPI
HTTP server ready to run with `make bootstrap`. See §10 (Project Retrospective) of
`docs/PROJECT_MEMORY.md` for the full wrap-up.

## What it does

When a production incident fires (alert, error spike, failed deploy), an on-call
engineer must triage the signal, retrieve relevant context (runbooks, past
postmortems, infra/code docs), diagnose root cause, propose a remediation, get it
approved, execute it, verify the fix, and write a postmortem. Sentinel automates the
diagnostic and drafting work end to end while keeping a human as the final authority
on any state-changing action.

## Why LangGraph

A linear retrieve → generate chain can't model this workflow: diagnosis is iterative
(self-RAG re-routes and re-retrieves on low relevance), execution can fail and force a
re-plan, the process must pause indefinitely for human approval and resume exactly
where it left off, and branching depends on model confidence and guardrail verdicts.
LangGraph's `StateGraph` — persistent state, conditional edges, cycles, durable
interrupt/resume — is the orchestration backbone for the whole app; LangChain supplies
component primitives (retrievers, loaders, prompts) inside graph nodes only.

## Architecture at a glance

```
entry -> guardrail_input -(unsafe)-> reject -> END
guardrail_input -(safe)-> router -> retriever -> reranker -> grade_documents
grade_documents -(low relevance, retries left)-> router        [self-RAG loop]
grade_documents -(ok)-> diagnose -> propose_action -> guardrail_output
guardrail_output -(unsafe)-> reject
guardrail_output -(safe, side-effecting)-> await_human_approval  [HITL interrupt]
guardrail_output -(safe, read-only)-> execute
await_human_approval -(approved)-> execute
await_human_approval -(rejected)-> diagnose
execute -(failure)-> diagnose
execute -(success)-> write_postmortem -> guardrail_output -> END
```

The full node-by-node contract lives in `docs/PROJECT_MEMORY.md` §5.2.

## The six production pillars

| Pillar | What it covers |
|---|---|
| 1. Advanced RAG Mechanics | Query routing (single-corpus v1), pgvector retrieval, `bge-reranker-base` cross-encoder re-ranking, self-RAG relevance grading with bounded retries |
| 2. Human-in-the-Loop | `interrupt()`-based `await_human_approval` node, `PostgresSaver` checkpointing, typed `{approved, modified_action, note}` resume contract |
| 3. Guardrails | Llama Guard 3-8B (local Ollama) at every entry/exit node, native `safe`/`unsafe\nSN` format parsed by a dual-parser with JSON fallback, dedicated red-team eval dataset |
| 4. LLM Evals | Versioned golden incident set, `ragas` retrieval metrics, LangSmith LLM-as-judge rubric evaluator, separate `make eval` CI gate |
| 5. AI Gateway | LiteLLM Proxy as the sole chokepoint for every model call — fallback chains, semantic caching (with an eval-determinism carve-out), per-key rate limits, trace-tagged cost logging |
| 6. Fine-Tuning | Contrastive fine-tune of `bge-small-en-v1.5` from retriever/reranker LangSmith traces, A/B-evaluated and promoted behind a config flag |

## Tech stack

| Layer | Choice |
|---|---|
| Orchestration | `langgraph` |
| LLM framework | `langchain` (components only) |
| Tracing / eval | `langsmith` |
| Gateway | `litellm` (proxy mode) |
| Guardrails | Llama Guard 3-8B (via gateway) |
| Vector store | Postgres + `pgvector` |
| Checkpointer | `langgraph-checkpoint-postgres` |
| Re-ranker | `BAAI/bge-reranker-base` (local) |
| Evals | `ragas` + LangSmith custom evaluators |
| Fine-tuning | `sentence-transformers` |
| Cache | Redis |
| API layer | FastAPI |
| Spec / BDD | `behave` (Gherkin) |
| Testing | `pytest` + `pytest-asyncio` |
| Local models | `ollama` (llama3.1, mistral-small, bge-m3, llama-guard3) |
| Local infra | `docker-compose` (Postgres, Redis, LiteLLM proxy, Ollama, mock-staging-api) |

## Repository layout

```
src/
  api/app.py                    # FastAPI HTTP server — POST /runs, POST /runs/{id}/approve
  gateway/client_factory.py     # sole construction path for every LLM/embedding client
  guardrails/check.py           # guardrail_check() — Llama Guard 3 (Ollama) via gateway
  graph/
    state.py                    # IncidentState TypedDict
    build.py                    # StateGraph assembly + PostgresSaver wiring
    checkpoint.py               # get_checkpointer() — PostgresSaver or in-memory fallback
    nodes/                      # one module per graph node
  ingestion/document_store.py   # get_document_store() — PostgresDocumentStore or in-memory
  retrieval/vector_search.py    # pgvector cosine search or plain-Python fallback
  tools/
    registry.py                 # tool name -> side_effecting flag
    executors.py                # tool dispatch against the mock staging API (httpx)
evals/
  golden_incidents.jsonl        # versioned eval set (reference root cause/remediation/rubric)
  judge_prompt.md               # LangSmith LLM-as-judge rubric prompt
  guardrail_redteam.jsonl       # labeled safe/unsafe examples for moderation accuracy
scripts/
  ingest_corpora.py             # corpus -> pgvector ingestion
  run_eval.py                   # eval harness mechanics + guardrail red-team dataset
  export_finetune_pairs.py      # LangSmith spans -> contrastive JSONL pairs
  finetune_embedding_model.py   # sentence-transformers contrastive fine-tune
  ab_eval_embedding_model.py    # base vs. fine-tuned promotion gate
  mock_staging_api/             # minimal FastAPI stub for the execute node's tool calls
infra/
  docker-compose.yml            # Postgres+pgvector, Redis, LiteLLM, Ollama, mock-staging-api
  litellm_config.yaml           # model aliases, fallback chains, rate limits
  schema.sql                    # one-time DB init: pgvector extension + documents table
memory/
  features/                     # one detail file per implemented feature (ADRs, Gherkin, PyTest)
docs/
  PROJECT_MEMORY.md             # the living architecture record — read this first
  SWAPPING_MODELS.md            # runbook: swapping a model behind a sentinel-* alias
  ...                            # MIGRATION_PLAN.md, USAGE.md, and other point-in-time artifacts
```

## Project memory

`docs/PROJECT_MEMORY.md` is this project's living architecture record: every Architecture
Decision Record, the Production RAG Blueprint, active state/graph/gateway contracts,
the Development Workflow Blueprint, and the prioritized feature roadmap. It is never
trimmed — superseded decisions are marked, not deleted — and it is the required
starting context for any new feature or session. Per-feature detail (conflict checks,
new ADRs, Gherkin, PyTest skeletons) lives in `memory/features/feature-NN-*.md`.
General project documentation (runbooks, reviews, migration plans) lives in `docs/`;
`memory/features/` keeps its own identity as the per-feature Living Memory record.

## Development workflow

This project is built spec-first, in a tight loop:

```
API/Schema Spec -> Gherkin (.feature) -> PyTest (unit + integration) -> Implementation -> Refactor
```

Tests are split into two tiers (`docs/PROJECT_MEMORY.md` §8.2):
- **Deterministic Tier** — structural/contract tests, fully mocked, blocks merge on
  failure (`pytest`).
- **Probabilistic Tier** — quality scores (`ragas`, LangSmith LLM-as-judge), gated
  against a versioned threshold in a separate `make eval` CI job, never asserted with
  `==`.

A feature is only checked off the roadmap once it passes the full Definition of Done
in §8.5 — Gherkin scenarios green, unit/integration tests passing, the relevant eval
baseline met, and the Feature Log row filled in.

## Running it

**First-time bootstrap** (credentials in `infra/.env`):
```bash
make bootstrap   # up → pull-local-models → init-db → ingest → smoke → serve
```

Individual steps:
```bash
make check-env          # validate credentials
make up                 # start all infra containers
make pull-local-models  # pull Ollama models (~14 GB, one-time)
make init-db            # apply infra/schema.sql to Postgres
make ingest             # embed corpora into pgvector
make smoke              # wiring check (no server)
make serve              # start API at http://localhost:8000
```

Without Docker (Deterministic Tier only):
```bash
make test-local         # 207/207 tests, no network required
make lint               # gateway-usage lint
```

## Status

All 14 Phase 4 roadmap items are **done** (ADR-007 through ADR-020). All stdlib
shims (ADR-021) have been replaced with conditional real-package imports (ADR-024):
`langgraph`, `langchain-openai`, `psycopg`, `sentence-transformers`, `httpx`, and
`langsmith` activate automatically when installed, falling back to the in-process
shims otherwise — so `make test-local` continues to pass (207/207) with no network
access. The HTTP API (`src/api/app.py`) is built and wired. `OPENAI_API_KEY` is the
only required external credential; all other models run locally via Ollama.
