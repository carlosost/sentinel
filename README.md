# Sentinel — Autonomous SRE Incident Copilot

Sentinel is a learning project for building a production-grade LLM application from
scratch with LangGraph, LangSmith, LangChain, and Advanced RAG — built under a strict
Spec-Driven Development → BDD → TDD workflow. **All 14 Phase 4 roadmap items are
implemented and tested** (190/190 tests passing). See §10 (Project Retrospective) of
`docs/PROJECT_MEMORY.md` for the full wrap-up, including what the sandbox this was built in
could and couldn't verify.

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
| 3. Guardrails | Llama Guard 3-8B at every entry/exit node, with binary `safe`/`unsafe` verdicts and a dedicated red-team eval dataset |
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
| Local infra | `docker-compose` (Postgres, Redis, LiteLLM proxy) |

## Repository layout

```
src/
  gateway/client_factory.py     # sole construction path for every LLM/embedding client
  guardrails/check.py           # guardrail_check() — Llama Guard via the gateway
  graph/
    state.py                    # IncidentState TypedDict
    build.py                    # StateGraph assembly + PostgresSaver wiring
    nodes/                      # one module per graph node
  tools/
    registry.py                 # tool name -> side_effecting flag
    executors.py                # tool dispatch against the mock staging API
evals/
  golden_incidents.jsonl        # versioned eval set (reference root cause/remediation/rubric)
  judge_prompt.md               # LangSmith LLM-as-judge rubric prompt
  guardrail_redteam.jsonl       # labeled safe/unsafe examples for moderation accuracy
  finetuning/                    # export_pairs.py, langsmith_spans.py, ab_eval.py
  embeddings/                    # finetuned_embeddings.py (local fine-tuned model shim)
scripts/
  ingest_corpora.py             # corpus -> pgvector ingestion
  run_eval.py                   # eval harness mechanics + guardrail red-team dataset
  export_finetune_pairs.py      # LangSmith spans -> contrastive JSONL pairs
  finetune_embedding_model.py   # sentence-transformers contrastive fine-tune
  ab_eval_embedding_model.py    # base vs. fine-tuned promotion gate
infra/
  docker-compose.yml            # Postgres+pgvector, Redis, LiteLLM proxy, mock-staging-api
  litellm_config.yaml           # model aliases, fallback chains, rate limits
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

- `python3 -m unittest discover -s tests` — full Deterministic Tier suite (190/190 passing).
- `python3 -m pyflakes src tests` (or your preferred linter) — lint check.
- `scripts/*.py` — most exit non-zero or print an explicit sandbox-limitation
  message rather than silently faking results; see docs/PROJECT_MEMORY.md §10 for
  which scripts do which, and why.

## Status

All 14 Phase 4 roadmap items are **done** (ADR-007 through ADR-020) — see §6
(Feature Log), §9 (Roadmap), and §10 (Retrospective) of `docs/PROJECT_MEMORY.md`.
Every feature is implemented and covered by Deterministic Tier tests, but none
has run against its real external dependency (LLM, vector DB, LangSmith, etc.)
— this sandbox has no PyPI/network/Docker egress, so every such dependency is
a stdlib stand-in shim (ADR-021) that raises `NotImplementedError`. That ADR-021
retrofit pass — swapping shims for real packages — is the honest next step.
