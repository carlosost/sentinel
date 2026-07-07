# Engineering Playbook: Production LLM Agentic Systems
## Project: Sentinel — Autonomous SRE Incident Copilot

**Scope:** This playbook synthesizes the complete build history of Sentinel — a
production-grade LangGraph + LangSmith + Advanced RAG system — into a reusable
organizational reference. It covers the pre-development contract process, the
AI-assisted development model, the full architecture with local model migration, and
the observability/evaluation strategy with annotated failure post-mortems.

**Intended audience:** Engineers, tech leads, and AI practitioners spinning up new
LLM-backed agentic systems who want to avoid the failure modes uncovered here.

---

## Table of Contents

1. [Pre-Development & Research Phase](#1-pre-development--research-phase)
2. [Cowork Interaction & Agentic Workflow Model](#2-cowork-interaction--agentic-workflow-model)
3. [Core Architecture & Local Model Migration](#3-core-architecture--local-model-migration)
4. [Production Observability & Lessons Learned](#4-production-observability--lessons-learned)

---

## 1. Pre-Development & Research Phase

### 1.1 The Problem With Starting With Code

The most expensive mistake in LLM system development is starting implementation before
the control flow is fully specified. LLM behavior is probabilistic; if the graph
structure that controls it is ambiguous, you discover the ambiguity at runtime — in
production — not in a test. This project used a Spec-Driven Development (SDD) approach:
every structural decision was made, written down, and conflict-checked against prior
decisions *before* the first line of implementation was written.

The artifact that enforced this is the **Project Memory Asset (PMA)** — `docs/PROJECT_MEMORY.md`.
It is a living document that contains:

- The project charter and problem statement
- All Architecture Decision Records (ADRs), including superseded ones (never deleted)
- The canonical graph skeleton (node names, edge conditions)
- The canonical state schema (field names, types, which ADR introduced each)
- A feature log keyed to per-feature spec files in `memory/features/`
- Open Questions with resolution status
- A retrospective

Every session began by reading the PMA. Every structural change was written into the
PMA before implementation. No feature was considered done until the PMA reflected it.

### 1.2 Why LangGraph Over Linear Chains

The decision to use LangGraph's `StateGraph` (ADR-001) is the project's foundational
technical choice. It was made before any code was written, by explicitly enumerating
the control-flow requirements and matching them against what linear chains can and
cannot express.

**Requirements that chains cannot model:**

| Requirement | Why a chain fails | How LangGraph handles it |
|---|---|---|
| Self-correcting retrieval (self-RAG) | Chains are acyclic; no loop-back path | Explicit cycle: `grade_documents → router` |
| Durable human approval | A chain step that blocks on external input has no persistence | `interrupt()` + PostgresSaver checkpointer |
| Execution failure re-planning | A chain cannot re-enter an earlier step with different input | `execute -(failure)→ diagnose` edge |
| Confidence-gated routing | Routing on model confidence requires state visible to the router | `diagnosis_confidence` field in shared `IncidentState` |
| Moderation at every boundary | Every chain step would need a wrapper | First-class guardrail nodes wired into the graph |

**The LangGraph mental model:**

Every processing step is a **node** — a pure function `(IncidentState) -> dict`. The
dict is a partial update; LangGraph merges it back into the shared state. All control
flow lives in **conditional edges** (routing functions), not inside nodes. This
separation means:
- Nodes are individually unit-testable with zero graph context.
- Control flow changes never require node changes, and vice versa.
- The graph structure is a first-class object, visible in LangSmith traces.

### 1.3 Spec-Driven Development: The ADR Process

Every structural decision is recorded as an **Architecture Decision Record** with:

```
### ADR-NNN: Title
- Context:     What problem or gap triggered this ADR.
- Decision:    The concrete, binding choice made.
- Consequences: What constraints this creates for future ADRs.
- Status:      Accepted | Superseded (never Deleted).
```

ADRs are additive and never rewritten. A superseded ADR stays in the PMA, marked
`Status: Superseded`, with a pointer to the superseding ADR. This matters because the
*reason* a decision was made is often more valuable than the decision itself, and
losing it means re-discovering the failure mode later.

**Critical ADRs established before any implementation:**

- **ADR-001** — LangGraph as the sole orchestration backbone. LangChain used only for
  component primitives (retrievers, loaders, prompt templates) inside nodes.
- **ADR-002** — PostgresSaver from day one. SQLite explicitly rejected even for local
  dev to prevent a checkpointer migration later.
- **ADR-003** — LiteLLM proxy as the only permitted path for every LLM/embedding call.
  No direct provider SDK access anywhere in the codebase.
- **ADR-004** — Guardrail hooks wired at every graph entry/exit from commit one,
  returning a stub `safe` verdict initially. The wiring is structural; the model
  decision is replaced later without touching the graph.
- **ADR-005** — Eval strategy requires ground truth. The original proposal ("LLM
  judges remediation quality") was self-critiqued and rejected before coding because
  it had no reference answer — an untestable eval masquerading as a pillar.
- **ADR-006** — A CI lint script (`scripts/lint_gateway_usage.sh`) enforces ADR-003.
  Any direct `openai`/`anthropic` import outside `src/gateway/` fails the build.

### 1.4 Enforcing Contracts Before Coding: The Conflict Check

Before implementing any feature, the implementing agent ran an explicit **Conflict
Check**: cross-referencing the new feature's spec against every existing ADR to
surface contradictions before they become bugs.

This step caught four real defects that would have shipped silently:

1. **ADR-005** — Caught that the original eval strategy had no ground truth. Enforced
   authoring `evals/golden_incidents.jsonl` (21 incidents with reference root cause,
   reference remediation, and binary rubric per criterion) before any node was built.
2. **ADR-009 / ADR-014** — Caught that `guardrail_output`'s rejection branch was never
   wired at either call site, despite being described in the pillar spec.
3. **ADR-019** — Caught two stale cross-references: ADR-004 pointing at the wrong
   Pillar number, and the `borderline` guardrail verdict in §8.3 that no ADR ever
   defined.
4. **ADR-020** — Caught that Pillar 6's fine-tuning data source (`grade_documents`'
   per-document relevance grade) didn't exist. ADR-012 only defined an *aggregate*
   batch grade; the pipeline was corrected to export from `retriever`/`reranker` spans
   instead.

None of these were caught by human re-reading. All four were caught by explicit
cross-referencing at the Conflict Check step.

### 1.5 The Golden Eval Set as a Pre-Implementation Contract

Per ADR-005/ADR-008, the evaluation dataset was authored before any graph node that
would be evaluated by it. The schema:

```jsonl
{
  "incident_id": "INC-001",
  "alert_text": "Disk usage at 95% on db-primary",
  "reference_root_cause": "Stuck logical replication slot accumulating WAL",
  "reference_remediation": {"tool": "restart_service", "args": {"service": "etl-consumer"}},
  "rubric": [
    {"criterion": "correct_root_cause", "description": "Identifies the replication slot as cause"},
    {"criterion": "safe_action", "description": "Proposed action is reversible or read-only"}
  ],
  "reference_docs": ["runbooks/disk-usage-high.md", "postmortems/2025-09-pm-wal-disk-exhaustion.md"]
}
```

The rubric uses binary yes/no criteria, never a 1–10 score. The judge prompt renders
one explicit question per criterion and requests `{"criterion": true|false}` JSON.
This is the mechanism that makes the eval deterministic enough to gate CI on.

---

## 2. Cowork Interaction & Agentic Workflow Model

### 2.1 The Iterative Development Loop

The project used a strict, four-step loop per feature, executed in sequence without
skipping:

```
[1] Spec → [2] Gherkin → [3] PyTest skeleton → [4] Implementation
              ↑                                         |
              └─────── Conflict Check ─────────────────┘
                  (cross-reference against all ADRs)
```

**Step 1 — Spec:** Update the PMA with the new ADR(s) before writing a single line
of Gherkin or code. The spec is the source of truth; the code is downstream of it.

**Step 2 — Gherkin:** Write `memory/features/feature-NN-name.md` with Behave/Gherkin
scenarios covering the happy path, the failure path, and any boundary conditions named
in the ADR. Tag scenarios:
- `@hitl` — must test both `approved` and `rejected` branches.
- `@guardrail` — verdicts are always mocked fixtures, never live model calls.
- `@gateway` — provider failures are simulated, never real outages.
- `@eval-gated` — a marker that documents a behavior covered by the probabilistic
  eval tier instead of a deterministic assertion.

**Step 3 — PyTest skeleton:** Write failing tests that mirror the Gherkin scenarios
before touching implementation. These tests define the node's observable contract: its
input shape, its output shape, and which state fields it reads vs. writes.

**Step 4 — Implementation:** Fill in the node. The tests are the specification; if
a test is ambiguous, the ambiguity is in the spec, and the spec is fixed before the
code is written — not worked around in the implementation.

### 2.2 The Two-Tier Test Strategy

Tests are split into two tiers with completely different semantics:

**Deterministic Tier** (`make test-local` / `python3 -m unittest discover -s tests`)

- Fully mocked: no network, no Docker, no live models.
- 100% pass rate is a hard gate — a single failure blocks merge.
- Every LLM client, embedding client, staging API client, and cross-encoder model
  is mocked at the factory function boundary, not the class boundary.
- Correct mocking pattern:
  ```python
  @patch("src.graph.nodes.router.get_chat_client")   # ✓ mock at the node's import path
  # not:
  @patch("src.gateway.client_factory.ChatOpenAI")   # ✗ mock at the class — breaks on shim swap
  ```

**Probabilistic Tier** (`make eval`)

- Real model calls, no mocking, separate CI job.
- Measures `context_precision`, `context_recall`, `faithfulness` via ragas.
- Measures end-to-end remediation correctness via LangSmith LLM-as-judge.
- Gated against a versioned baseline stored in the Feature Log, never asserted with `==`.
- **Never asserted with `==`.** Scores fluctuate; the gate is "≥ recorded baseline."

**Pillar-to-tier mapping:**

| Pillar | Deterministic Tier | Probabilistic Tier |
|---|---|---|
| Advanced RAG | Retriever/reranker call contracts, routing edge selection | Retrieval relevance, groundedness, self-RAG improvement |
| HITL | Interrupt trigger, checkpoint persistence, resume routing | N/A |
| Guardrails | Verdict-to-route wiring | Llama Guard moderation precision/recall |
| Evals | Dataset schema validity, evaluator registration | The eval scores themselves |
| AI Gateway | Fallback/caching/rate-limit config contracts | N/A |
| Fine-Tuning | Export pipeline shape/correctness | Fine-tuned vs. base model performance delta |

### 2.3 Context Preservation Across Long-Running Sessions

LLM context windows are finite. Multi-session projects require deliberate context
management to prevent the AI from making decisions that contradict earlier ADRs.

**The Project Memory Asset (PMA) as a context injector:**

Every session begins with: `"Read docs/PROJECT_MEMORY.md in full before making any
structural change."` This is not optional guidance — it is the first instruction in
every session prompt. The PMA contains all ADRs, the graph skeleton, the state schema,
the feature log, and open questions. A new session reading the PMA starts with the
same context as the session that wrote it.

**What must always be in a session-starting prompt:**

```
1. Read docs/PROJECT_MEMORY.md.
2. Read memory/features/feature-NN-name.md if continuing a specific feature.
3. The specific task: "[verb] [object] per [ADR reference]."
4. The Definition of Done for this task.
5. "Do not change any existing ADR, graph edge, or state field without first
   recording the change as a new or updated ADR in the PMA."
```

**The Living Memory update rule:**

Every session that changes an ADR, graph structure, state schema, or feature status
must update the PMA in the same response as the code change. Never defer PMA updates
to a follow-up — the PMA is only useful if it reflects the current state.

### 2.4 Safe AI Edits: The Regression-Prevention Protocol

Allowing an AI agent to edit core specifications (the PMA, the state schema,
`litellm_config.yaml`, the lint script) introduces regression risk. The protocol:

**1. Additive-only changes to state schema.**
New fields are added with `Optional[T]` and a default of `None`. Existing fields are
never renamed or retyped without an explicit ADR that documents the blast radius.
Any rename that touches node code also triggers a full test run before commit.

**2. Conflict Check before any structural change.**
Before the AI modifies any of: `src/graph/build.py`, `src/graph/state.py`,
`infra/litellm_config.yaml`, or `scripts/lint_gateway_usage.sh`, it explicitly
lists every existing ADR that the change might conflict with. If a conflict exists,
the ADR is updated first; the code change follows.

**3. Run `make test-local` after every file edit session.**
The deterministic tier completes in under 1 second (no network). There is never a
reason to defer running it. The correct session-ending protocol:
```bash
make test-local   # must be 207/207 (or new baseline)
make lint         # must pass
```

**4. Mock at the factory boundary, never the class.**
If a test mocks `ChatOpenAI` directly instead of `get_chat_client`, it will silently
break when the factory's implementation is swapped (shim → real package, or vice
versa). The factory boundary is the contract; mock it, not its internals.

**5. Prompt structure for safe codebase edits:**
```
Context: [paste the relevant ADR + state schema fields the node reads/writes]
Task: Implement [node name] per ADR-NNN.
Constraints:
  - Read state fields: [list]
  - Write state fields: [list] (partial dict only)
  - Must NOT call get_chat_client/get_embedding_client directly — use the
    factory function already imported at the top of the module.
  - The node function signature is: def node_name(state: IncidentState) -> dict:
Definition of Done: [paste §8.5 from PMA]
After implementation: run `python3 -m unittest tests/graph/nodes/test_<name>.py -v`
  and paste the output.
```

### 2.5 Managing Long-Running Agentic Tasks

Tasks that require multiple tool calls (file reads, writes, test runs, bash commands)
and span multiple minutes need explicit structure to avoid mid-task context loss.

**Task list before execution.** For any task with more than 3 tool calls, create an
explicit task list first. Declare each subtask and its acceptance criterion before
beginning. This prevents the agent from partially completing a task and losing track
of what remains when approaching its context limit.

**Checkpoint-and-continue protocol.** When a session approaches its context limit
mid-task:
1. Ask for a summary of what was completed, what is pending, and what the next
   concrete action is.
2. Start a fresh session with: "Continuing from [checkpoint]. State: [completed
   items]. Next action: [specific next step]."

**Never ask "did it work?" — verify programmatically.** After any code change, the
agent runs the test suite and pastes the output. A response of "this should work"
without a test run is not acceptable. The output of `make test-local` is the
acceptance criterion.

---

## 3. Core Architecture & Local Model Migration

### 3.1 Stack Overview

| Layer | Technology | Decision rationale |
|---|---|---|
| Orchestration | `langgraph` `StateGraph` | Cyclic state machine + native interrupt/resume |
| LLM framework | `langchain` (components only) | Retriever/loader primitives inside nodes; never top-level control flow |
| Tracing / eval | `langsmith` | Multi-node trace stitching, dataset management, LLM-as-judge |
| Gateway | `litellm` (proxy mode) | Single chokepoint: fallback chains, semantic caching, rate limits |
| Guardrails | Llama Guard 3-8B | Open-weight, purpose-built moderation classifier via gateway |
| Vector store | Postgres + `pgvector` | One database for both corpus vectors and HITL checkpoints |
| Checkpointer | `langgraph-checkpoint-postgres` | Durable interrupt state across process restarts |
| Re-ranker | `BAAI/bge-reranker-base` | Local in-process; zero extra API dependency on the hot path |
| Evals | `ragas` + LangSmith custom evaluators | Retrieval metrics + rubric-based end-to-end judge |
| Fine-tuning | `sentence-transformers` | Contrastive fine-tune of the embedding model from trace data |
| Cache | Redis | Backing store for LiteLLM semantic cache |
| API layer | FastAPI + `asyncio` | Async-native; graph runs in `asyncio.to_thread()` |
| Local models | Ollama (host, not Docker) | Metal GPU access on Apple Silicon |

### 3.2 Graph State Machine Architecture

The application is a **LangGraph `StateGraph`** with a single shared typed state
(`IncidentState` TypedDict) and twelve nodes:

```
entry → guardrail_input ─(unsafe)→ reject → END
                        ─(safe)→ router → retriever → reranker → grade_documents
grade_documents ─(low relevance, retries < 2)→ router          [self-RAG cycle]
               ─(ok or retries exhausted)→ diagnose
diagnose → propose_action → guardrail_output
guardrail_output ─(unsafe)→ reject
                ─(safe, side-effecting)→ await_human_approval   [HITL interrupt]
                ─(safe, read-only)→ execute
await_human_approval ─(approved)→ execute
                     ─(rejected)→ diagnose
execute ─(failure)→ diagnose
       ─(success)→ write_postmortem → guardrail_output → END
```

**Key structural invariants:**

- Nodes are pure functions: `(IncidentState) -> dict`. No node holds instance state.
- All control flow is in conditional edges (routing functions). No node branches internally.
- `side_effecting` on `proposed_action` is always read from `TOOL_REGISTRY`, never from
  the LLM response. This trust boundary prevents a hallucinated or prompt-injected
  `"side_effecting": false` from bypassing the human approval gate.
- `guardrail_output` is a single node reused at two call sites. It self-detects its
  position by checking whether `execution_result` is set in state.

### 3.3 Architectural Patterns Applied

The codebase applies five named patterns consistently across all modules:

**Factory** — The sole construction path for every runtime dependency.

```python
# Every external dependency is obtained through a factory function.
# No node ever instantiates a class directly.
client = get_chat_client(model="sentinel-router")       # LLM client
store  = get_document_store(database_url)               # document store
model  = get_reranker_model("BAAI/bge-reranker-base")   # cross-encoder (cached)
cp     = get_checkpointer(database_url)                 # checkpointer
api    = get_staging_api_client()                       # staging API client
```

This pattern makes every dependency swappable (real ↔ shim) at a single seam, and
makes every node independently mockable in tests by patching the factory function at
the node's own import path.

**Gateway** — Two-layer chokepoint for all LLM/embedding traffic.

```
Code level:   src/gateway/client_factory.py  ← factory functions; injected proxy URL + trace metadata
Infra level:  LiteLLM proxy (port 4000)      ← fallback chains, semantic cache, rate limits
```

The CI lint (`scripts/lint_gateway_usage.sh`) enforces this at build time — any
direct `openai`/`anthropic` import outside `src/gateway/` fails the build.

**Repository** — Storage abstraction for the corpus document store.

`InMemoryDocumentStore` and `PostgresDocumentStore` share the same interface
(`upsert`, `count`, `rows_for_corpus`). Callers reference neither class by name;
`get_document_store(database_url)` selects the backend. Swapping to Postgres is a
one-line caller change.

**Strategy** — Conditional implementation selection behind a shared interface.

The shim system (ADR-021/ADR-024) uses this pattern: `_ChatClient` (stdlib shim) and
`ChatOpenAI` (real) implement the same `invoke()` surface. The factory selects the
strategy at import time based on whether the real package is installed. Tests patch
the factory, not the strategy class.

**Adapter** — Interface translation at the real package boundary.

`_ContentUnwrappingChatClient` adapts `langchain_openai.ChatOpenAI.invoke()` —
which returns an `AIMessage` object — to the `str` interface every node was written
against:

```python
class _ContentUnwrappingChatClient:
    def invoke(self, *args, **kwargs) -> str:
        result = self._client.invoke(*args, **kwargs)
        return result.content if hasattr(result, "content") else str(result)
```

This single wrapper means zero node changes when swapping from the stdlib shim to
the real package.

### 3.4 FastAPI Async Patterns

The HTTP API (`src/api/app.py`) uses FastAPI with three design decisions:

**Graph execution in a thread pool.** `graph.invoke()` is synchronous (LangGraph's
default interface). Running it directly in an `async def` endpoint blocks the event
loop. The correct pattern:

```python
import asyncio, functools

@app.post("/runs")
async def start_run(req: StartRunRequest) -> StartRunResponse:
    invoke_fn = functools.partial(graph.invoke, initial_state, config=config)
    result = await asyncio.wait_for(
        asyncio.to_thread(invoke_fn),
        timeout=GRAPH_TIMEOUT,   # default 120s, configurable via GRAPH_TIMEOUT_SECONDS
    )
```

`functools.partial` is necessary because `asyncio.to_thread` takes a callable and
positional args — keyword arguments like `config=` cannot be passed directly.

**In-memory run store for status polling.** A `_run_store: Dict[str, dict]` tracks
`thread_id → status` so `GET /runs/{thread_id}` can return status without querying
the checkpointer. This is not durable across server restarts; durable state lives
in the PostgresSaver checkpointer.

**Timeout returns 504, not 500.** A graph that times out has not crashed — it simply
didn't complete within the budget. HTTP 504 (Gateway Timeout) is semantically correct;
the client can retry or poll.

### 3.5 Local Model Migration (ADR-023)

The project migrated all paid fallback models (Anthropic, Cohere) to locally-served
open-weights models via Ollama. This is a four-phase strategy reusable for any
LiteLLM-gated system.

**Phase 1 — Infra: Add Ollama, keep paid fallbacks live.**

Add Ollama to `infra/docker-compose.yml` as a new service. Do not touch the existing
`litellm_config.yaml` fallback entries yet. Pull models with `ollama pull`.

**Phase 2 — Alias repoint: Swap fallback model strings.**

In `litellm_config.yaml`, change each `*-fallback` alias's `model:` from the paid
string to the Ollama provider string:

```yaml
# Before:
- model_name: sentinel-router-fallback
  litellm_params:
    model: anthropic/claude-haiku-20240307

# After:
- model_name: sentinel-router-fallback
  litellm_params:
    model: ollama_chat/llama3.1:8b-instruct-q4_K_M
    api_base: http://ollama:11434
    format: json
```

Zero changes to `src/`. Every node was already provider-agnostic (ADR-003); this is
a YAML edit only.

**Phase 3 — Embedding dimension mismatch: Fail loudly, not silently.**

If the primary embedding model (`text-embedding-3-small`, 1536-dim) fails over to a
local model (`bge-m3`, 1024-dim), a query embedding at 1024-dim will silently produce
wrong cosine-similarity results against a 1536-dim index. The correct fix is to make
this a named, hard-failing exception:

```python
class EmbeddingDimensionMismatchError(ValueError):
    """Raised when query embedding dimension doesn't match the corpus index."""

def cosine_similarity(a: list, b: list) -> float:
    if len(a) != len(b):
        raise EmbeddingDimensionMismatchError(
            f"Query embedding dim {len(a)} != corpus dim {len(b)}"
        )
```

The `retriever` node does not catch this exception — it propagates, surfacing as a
visible node failure, not a silently wrong answer.

**Phase 4 — Shadow validation, then cutover.**

Before revoking paid API keys, shadow a small fraction of real requests to the local
model and compare against the paid primary's responses using the LangSmith judge. This
validates local model quality under real traffic before full cutover.

**Phase 5 (Sentinel-specific) — Ollama on host for Metal GPU.**

Running Ollama inside Docker on macOS Apple Silicon means CPU-only inference (~24s
per guardrail call). Moving Ollama to the host gives Metal GPU access and drops
latency to ~70ms — a 347× improvement.

Configuration: in `litellm_config.yaml`, set `api_base: http://host.docker.internal:11434`.
Containers reach the host-side Ollama via Docker's `host.docker.internal` DNS alias.

```yaml
environment:
  OLLAMA_BASE_URL: "http://host.docker.internal:11434"
```

Start Ollama on the host with:
```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

### 3.6 The Conditional Import / Shim System (ADR-021/ADR-024)

Environments without PyPI access (air-gapped CI, sandboxed development) cannot install
`langgraph`, `langchain-openai`, etc. The conditional import pattern maintains a fully
testable codebase in these environments while activating real packages when installed:

```python
try:
    from langchain_openai import ChatOpenAI as _RealChatClient
    _LANGCHAIN_OPENAI_AVAILABLE = True
except ImportError:
    _LANGCHAIN_OPENAI_AVAILABLE = False

def get_chat_client(model: str, **kwargs):
    if _LANGCHAIN_OPENAI_AVAILABLE:
        return _ContentUnwrappingChatClient(_RealChatClient(model=model, ...))
    return _ChatClient(model_name=model, ...)   # stdlib shim
```

**Key invariant:** installing the real package is the only required action. No code
changes at call sites. Tests continue to pass unchanged because they mock at the
factory boundary, not the class.

---

## 4. Production Observability & Lessons Learned

### 4.1 LangSmith Tracing Strategy

LangSmith tracing is enabled via environment variables — no `@traceable` decorators
needed on individual functions:

```yaml
# docker-compose.yml app service environment:
LANGSMITH_TRACING: "true"
LANGSMITH_ENDPOINT: "https://api.smith.langchain.com"
LANGSMITH_API_KEY: ${LANGSMITH_API_KEY}
LANGSMITH_PROJECT: ${LANGSMITH_PROJECT:-sentinel}
```

LangGraph auto-instruments all node executions. Every node appears as a named span in
the trace tree. The `trace_id` from LangSmith is propagated into every LiteLLM proxy
request as `metadata={"trace_id": ...}`, joining gateway cost/usage logs to the
LangSmith trace:

```python
def _with_trace_metadata(kwargs: dict) -> dict:
    metadata = dict(kwargs.get("metadata") or {})
    metadata.setdefault("trace_id", get_current_trace_id())
    return {**kwargs, "metadata": metadata}
```

**Env var naming:** LangSmith renamed its environment variables in mid-2025.
`LANGCHAIN_API_KEY` and `LANGCHAIN_PROJECT` are no longer honoured. Use
`LANGSMITH_API_KEY` and `LANGSMITH_PROJECT`. Using the old names causes a silent
fall-through to the in-process shim — no error, no tracing.

### 4.2 Ragas Evaluation Integration

Ragas measures retrieval quality on the golden eval set. The three metrics used:

| Metric | What it measures | Target |
|---|---|---|
| `context_precision` | Fraction of retrieved docs that are relevant | ≥ recorded baseline |
| `context_recall` | Fraction of reference docs successfully retrieved | ≥ recorded baseline |
| `faithfulness` | Generated answer grounded in retrieved context | ≥ recorded baseline |

**Eval-determinism carve-out:** LiteLLM's semantic cache is enabled proxy-wide for
application traffic. Without an explicit bypass, an eval run could hit a cached
stale response and mask a real model behavior regression. All eval harness calls pass:

```python
client = get_chat_client(model="sentinel-judge", cache={"no-cache": True})
```

This is the only permitted exception to the semantic cache — never bypass it in
application nodes.

### 4.3 LangSmith CI Assertions

**Build-blocking (structural):**
- Node execution order matches the expected sequence for each scenario.
- Every model-call span carries gateway metadata (proxy host/route) — enforces ADR-003
  is not silently bypassed.
- Per-node latency stays within a budget in the mocked CI environment.

**Logged only (non-blocking):**
- Generated diagnosis text and remediation rationale.
- LLM-as-judge qualitative rationale (the pass/fail *score* is blocking; the rationale
  text is for human review).
- Full self-RAG retry transcripts.

### 4.4 Lessons Learned & Anti-Patterns

The following failures were encountered in actual end-to-end runs. Each is
documented with its root cause and the specific fix applied.

---

#### AP-01: LLM Hallucinating Tool Names

**Symptom:** `propose_action` raises `ProposeActionError: 'kubectl' is not a known tool`
on every real-infra run.

**Root cause:** The prompt enumerated the task ("propose a remediation") without
listing valid tool names. The LLM drew from its training data and returned `kubectl`,
a widely-known tool that is not in `TOOL_REGISTRY`.

**Fix:** Enumerate valid tool names in the prompt at call time, generated from the
registry:

```python
def _format_tool_list() -> str:
    return "\n".join(
        f"  - {name} ({'side-effecting' if spec['side_effecting'] else 'read-only'})"
        for name, spec in TOOL_REGISTRY.items()
    )

prompt = f"You MUST choose from the following tools only:\n{_format_tool_list()}\n..."
```

**Lesson:** Any prompt that expects a value from a finite enumeration must include that
enumeration in the prompt. Never assume the model knows what's valid.

---

#### AP-02: Ingest and Retrieval Using Different Store Instances

**Symptom:** `retrieved_docs` is always `[]` after a successful `make ingest`.

**Root cause:** `scripts/ingest_corpora.py` was hardcoded to `InMemoryDocumentStore()`.
The `retriever` node's `get_document_store(DATABASE_URL)` returns a
`PostgresDocumentStore`. Two different backends, no shared data.

**Fix:**
```python
# Before:
store = InMemoryDocumentStore()

# After:
database_url = os.environ.get("DATABASE_URL")
store = get_document_store(database_url)  # same factory the retriever uses
```

**Lesson:** All write paths and all read paths for a shared data store must go through
the same factory function. Any hardcoded instantiation bypasses this guarantee.

---

#### AP-03: Real Package Returns Typed Objects, Not Strings

**Symptom:** `AttributeError: 'AIMessage' object has no attribute 'strip'` on every
live model call; nodes calling `.strip()` or `json.loads()` on the result.

**Root cause:** Every node was written against the stdlib shim's `invoke()` contract,
which returned a plain `str`. The real `langchain_openai.ChatOpenAI.invoke()` returns
an `AIMessage` object. The mismatch was invisible during testing (shim returned `str`)
and only appeared when real packages were installed.

**Fix:** Adapter pattern at the factory boundary, not changes to every node:

```python
class _ContentUnwrappingChatClient:
    def invoke(self, *args, **kwargs) -> str:
        result = self._client.invoke(*args, **kwargs)
        return result.content if hasattr(result, "content") else str(result)
```

**Lesson:** When integrating a real SDK against a hand-written shim, validate the
actual return type of every method at the integration boundary. Never assume the real
SDK has the same calling convention as the shim — adapt at one seam rather than
updating every call site.

---

#### AP-04: PostgresSaver.setup() Fails Inside a Transaction Block

**Symptom:** `CREATE INDEX CONCURRENTLY cannot run inside a transaction block` on
first startup.

**Root cause:** `PostgresSaver.setup()` creates a `CREATE INDEX CONCURRENTLY`
statement, which Postgres forbids inside a transaction. `psycopg` defaults to
`autocommit=False`, wrapping every statement in a transaction.

**Fix:**
```python
conn = psycopg.connect(database_url, autocommit=True)
return PostgresSaver(conn)
```

**Lesson:** `CREATE INDEX CONCURRENTLY` always requires `autocommit=True`. Any
psycopg connection used to run DDL of this form must not be in transaction mode.

---

#### AP-05: tiktoken Fails on LiteLLM Alias Names

**Symptom:** `KeyError: 'sentinel-embedding'` from tiktoken during embedding calls.

**Root cause:** `langchain_openai.OpenAIEmbeddings` uses tiktoken to pre-count tokens
before sending the request. tiktoken does not recognize LiteLLM alias names (e.g.,
`sentinel-embedding`) and attempts to fetch vocabulary files from the internet —
failing in air-gapped environments, or raising a `KeyError` for unknown model names.

**Fix:**
```python
return OpenAIEmbeddings(
    model=model,
    openai_api_base=proxy_url,
    check_embedding_ctx_length=False,  # disables tiktoken pre-check
    ...
)
```

**Lesson:** LiteLLM alias names are not recognized by any tool that reads OpenAI's
model registry (tiktoken, some LangChain validators). Always disable model-name-based
pre-validation when routing through a proxy.

---

#### AP-06: Unknown Kwargs Forwarded to the OpenAI API

**Symptom:** `TypeError: Embeddings.create() got an unexpected keyword argument 'metadata'`

**Root cause:** `_with_trace_metadata()` adds `metadata` to every client's kwargs.
`OpenAIEmbeddings` does not consume unknown kwargs — it passes them to `model_kwargs`,
which are forwarded directly to the OpenAI API, which does not accept `metadata`.

**Fix:** Strip `metadata` before constructing the embedding client:

```python
embedding_extra = {k: v for k, v in extra.items() if k != "metadata"}
return OpenAIEmbeddings(..., **embedding_extra)
```

Trace metadata for embedding calls is still captured by LangSmith's auto-instrumentation
on the surrounding `traced_run()` context.

**Lesson:** Trace metadata injection at a shared utility level (`_with_trace_metadata`)
can cause type errors in clients that forward unknown kwargs to downstream APIs. Always
strip non-API kwargs before constructing provider-specific clients.

---

#### AP-07: Ollama in Docker = CPU-Only Inference

**Symptom:** Guardrail calls taking 24 seconds each; end-to-end run taking 6+ minutes.

**Root cause:** Ollama running inside Docker on macOS Apple Silicon uses CPU inference.
Docker Desktop on macOS cannot pass through the Metal GPU to containers.

**Fix:** Move Ollama to the host and have Docker containers reach it via
`host.docker.internal`:

```bash
# Terminal 1 (keep running)
OLLAMA_HOST=0.0.0.0 ollama serve

# docker-compose.yml litellm service:
OLLAMA_BASE_URL: "http://host.docker.internal:11434"
```

**Result:** Latency dropped from ~24s to ~70ms per guardrail call (347× speedup from
Metal GPU + KV cache hits).

**Lesson:** Never run Ollama inside Docker on macOS. The macOS Metal GPU is only
accessible to native processes. This applies to any GPU-dependent local inference
(vLLM, llama.cpp, etc.).

---

#### AP-08: Missing Port in Service URL

**Symptom:** `[Errno 111] Connection refused` on every execute node call.

**Root cause:** `http://mock-staging-api` without a port defaults to port 80.
The mock service binds to port 8001.

**Fix:**
```python
_DEFAULT_BASE_URL = "http://mock-staging-api:8001"
```

**Lesson:** Always specify ports explicitly in service-to-service URLs inside Docker
networks. Docker's internal DNS resolves service names, but port defaulting to 80
applies even within a compose network.

---

#### AP-09: LangSmith Env Var Rename Silently Disables Tracing

**Symptom:** Traces not appearing in LangSmith despite `LANGCHAIN_API_KEY` being set.

**Root cause:** LangSmith renamed its environment variables in mid-2025:
`LANGCHAIN_API_KEY` → `LANGSMITH_API_KEY`, `LANGCHAIN_PROJECT` → `LANGSMITH_PROJECT`.
The old names are silently ignored — no warning, no error, no tracing.

**Fix:** Update all configuration files:
```bash
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=sentinel
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

Also update any code that reads the old env vars:
```python
# Before:
if os.environ.get("LANGCHAIN_API_KEY"):
# After:
if os.environ.get("LANGSMITH_API_KEY"):
```

**Lesson:** LLM framework env var names are not stable across versions. Pin your
env var names to the documentation for your installed package version, not your memory
of a previous version's tutorial.

---

#### AP-10: Cross-Encoder Loaded on Every Request

**Symptom:** ~2-4 second latency added to every request; ~500 MB of memory allocated
and freed on each call.

**Root cause:** `get_reranker_model()` was constructing a new `CrossEncoder` instance
on every call. `sentence_transformers` loads the full model weights from disk on
construction.

**Fix:** Module-level cache:
```python
_MODEL_CACHE: dict = {}

def get_reranker_model(model_name: str = "BAAI/bge-reranker-base"):
    if model_name not in _MODEL_CACHE:
        _MODEL_CACHE[model_name] = _RealCrossEncoder(model_name)
    return _MODEL_CACHE[model_name]
```

**Lesson:** Any local model loaded from disk (cross-encoder, embedding model, guard
model) must be cached at module level, not reconstructed per request. The singleton
is intentional; it is not a global state risk because the model is stateless — it only
carries weights.

---

### 4.5 Numeric Placeholders That Require Empirical Grounding

Four thresholds were shipped as documented placeholder values. **Do not treat these
as tuned parameters in a production deployment**:

| Parameter | Placeholder value | Where to tune |
|---|---|---|
| Self-RAG relevance threshold | `< 0.6` | After eval baseline on golden set |
| LiteLLM virtual-key rate limits | Arbitrary | After real usage/cost data exists |
| Guardrail precision/recall gate | No threshold set | After Llama Guard red-team scorer runs |
| Fine-tuning promotion margin | `PROMOTION_MARGIN = 0.05` | After first A/B eval run |

The mechanism for each is implemented and tested. The number is provisional.

### 4.6 The Shim Risk: What "Tests Passing" Actually Means

The project was developed under PyPI-access constraints and used stdlib shims for
`langgraph`, `langchain-openai`, `psycopg`, `sentence-transformers`, and `httpx`.
When all 207 tests pass, it means the code behaves correctly *against the shims*.

Before trusting any test result as a claim about production behavior:

1. Swap every shim for the real package.
2. Re-run the full test suite.
3. Specifically verify: cycle behavior (`grade_documents → router`), interrupt/resume
   semantics (`await_human_approval`), and the `AIMessage` → `str` unwrapping
   (`_ContentUnwrappingChatClient`).

This project resolved this via **ADR-024 conditional imports** — the shims activate
only when the real packages are not installed. Installing `langchain-openai` alone
activates the real clients with zero code changes. The `_ContentUnwrappingChatClient`
adapter was the only behavioral change required.

---

## Appendix: Reusable Prompt Templates

### A.1 Session-Opening Prompt (New Feature)

```
Read docs/PROJECT_MEMORY.md in full.
Read memory/features/feature-NN-name.md.

Task: Implement [node name] per ADR-NNN.

State fields this node reads: [list from §5.1]
State fields this node writes: [list from §5.1]

Constraints:
- Node signature: def [name](state: IncidentState) -> dict:
- Obtain LLM client via get_chat_client(model="sentinel-<alias>") only.
- Do not modify any existing ADR, graph edge, or state field without first
  recording the change as a new or amended ADR in docs/PROJECT_MEMORY.md.
- Mock target in tests: @patch("src.graph.nodes.[name].get_chat_client")

Definition of Done (from §8.5):
1. PMA updated in the same response as the code.
2. All Gherkin scenarios pass in the Deterministic Tier (fully mocked).
3. Unit test covers state-transition contract.
4. make test-local output pasted (must be N/N passing).
```

### A.2 Session-Opening Prompt (Bug Fix)

```
Read docs/PROJECT_MEMORY.md §2 (ADRs) and §7 (Open Questions).

Bug: [describe symptom + full stack trace or error message]

Before proposing a fix:
1. Identify which ADR's contract the bug violates, if any.
2. If the fix changes a contract (state schema, node interface, gateway config),
   record it as a new or amended ADR first.
3. If the fix does not change a contract, implement it and run make test-local.

After fix: paste make test-local output.
```

### A.3 Local Model Migration Checklist

```
[ ] 1. Ollama running on host: OLLAMA_HOST=0.0.0.0 ollama serve
[ ] 2. Models pulled: make pull-local-models
[ ] 3. litellm_config.yaml: *-fallback aliases point to ollama_chat/* provider strings
[ ] 4. docker-compose.yml: OLLAMA_BASE_URL=http://host.docker.internal:11434
[ ] 5. check_env.sh: paid provider API keys removed from REQUIRED_VARS
[ ] 6. .env.example updated; paid key vars commented out with revocation date
[ ] 7. make test-local: N/N passing
[ ] 8. make smoke: gateway wiring check passes
[ ] 9. make ingest: corpus embedded with new fallback model
[ ] 10. Paid API keys revoked at provider dashboards (attestation required)
```
