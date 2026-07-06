# Production Readiness Plan

**Written:** 2026-07-05
**Scope:** Three phases to get from the current sandbox-shim state to a system that can actually run: (1) replace every `NotImplementedError` stub with its real package, (2) build the missing HTTP API, (3) boot real infrastructure. Phases 1 and 3 are partially parallel — you need infra running to verify Phase 1 replacements, but the code changes themselves don't require it yet.

---

## Phase 1 — Swap the Shims

Do these in dependency order. Gateway first (every node calls it), then LangGraph (graph execution), then Postgres (checkpointer + document store), then local models (reranker, fine-tuned embeddings), then the remaining peripheral modules.

### 1.1 Install real packages

```bash
pip install -r requirements.txt
```

All real packages are already declared — `langgraph`, `langchain-openai`, `langsmith`, `sentence-transformers`, `psycopg[binary]`, `ragas`, `httpx`. Nothing needs to be added; the shims exist because the dev sandbox couldn't install them.

### 1.2 Gateway clients (`src/gateway/client_factory.py`)

Delete the `_ChatClient` and `_EmbeddingClient` dataclasses and replace their construction in `get_chat_client`/`get_embedding_client` with the real classes:

```python
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# get_chat_client returns:
return ChatOpenAI(
    model=model,
    openai_api_base=_proxy_base_url(),
    openai_api_key=_virtual_key() or "unset",
    **_with_trace_metadata(kwargs),
)

# get_embedding_client returns:
return OpenAIEmbeddings(
    model=model,
    openai_api_base=_proxy_base_url(),
    openai_api_key=_virtual_key() or "unset",
    **_with_trace_metadata(kwargs),
)
```

The public surface these return (`.model_name`, `.model`, `.openai_api_base`, `.invoke()`, `.embed_documents()`) is identical to what the shims exposed — every call site in nodes and tests should be unaffected. Verify with `make test-local` immediately after; any breakage here is a sign a node was relying on something shim-specific.

Node tests mock `get_chat_client` at the import path (`@patch("src.graph.nodes.router.get_chat_client")`) and don't call `.invoke()` on a real client, so the Deterministic Tier passes regardless of this swap. What this unlocks is real LLM calls once the proxy is running.

### 1.3 LangGraph (`src/graph/_compat.py`)

Replace the entire import in `src/graph/build.py` and `src/graph/nodes/await_human_approval.py`:

```python
# Before (shim):
from src.graph._compat import StateGraph, START, END, interrupt, GraphInterrupt

# After (real):
from langgraph.graph import StateGraph, START, END
from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt
```

Then delete `src/graph/_compat.py`. The shim was designed to mirror real langgraph's API shapes exactly, so the graph structure in `build.py` (`add_node`, `add_edge`, `add_conditional_edges`, `compile(checkpointer=...)`) requires no changes.

**Critical verification:** the `await_human_approval` node is written around the shim's limitation — it checks `state.get("human_decision")` on re-entry rather than using `interrupt()`'s return value. Real langgraph's `interrupt()` *does* return a value on resume via generator-replay, but the node's check-state pattern still works correctly with real langgraph (re-running the node is safe and side-effect-free). Still, run `tests/graph/test_hitl_checkpoint_restart.py` with a real `PostgresSaver` (Phase 1.4) before declaring this done.

### 1.4 Postgres checkpointer (`src/graph/checkpoint.py`)

Replace `InMemoryCheckpointSaver` with `PostgresSaver` at the graph-construction call site. The shim's `save`/`load`/`exists`/`clear` interface is custom — the real `PostgresSaver` is initialized differently:

```python
from langgraph.checkpoint.postgres import PostgresSaver
import psycopg

# At startup (e.g. in the FastAPI lifespan or a build_graph() wrapper):
conn = psycopg.connect(os.environ["DATABASE_URL"])
checkpointer = PostgresSaver(conn)
checkpointer.setup()          # creates the required tables on first run
graph = build_graph(checkpointer=checkpointer)
```

The `checkpointer.setup()` call is idempotent — safe to run every startup. The `DATABASE_URL` is already declared in `infra/docker-compose.yml` (`postgresql://sentinel:sentinel@postgres:5432/sentinel`).

Delete `src/graph/checkpoint.py` once the real checkpointer is wired.

### 1.5 Document store + vector search (`src/ingestion/document_store.py` + `src/retrieval/vector_search.py`)

These two shims work together and must be replaced together. The real backing is a `documents` table in Postgres with a pgvector `embedding` column:

```sql
-- Run once, after `make up`:
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    corpus      TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(1536),   -- must match sentinel-embedding's output dimension
    metadata    JSONB
);
CREATE INDEX IF NOT EXISTS documents_embedding_idx
    ON documents USING ivfflat (embedding vector_cosine_ops);
```

Replace `InMemoryDocumentStore.upsert()` with a `psycopg` insert-or-update:

```python
# upsert:
conn.execute(
    "INSERT INTO documents (id, corpus, content, embedding, metadata) "
    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE "
    "SET embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata",
    (content_hash(content), corpus, content, embedding, json.dumps(metadata or {}))
)
```

Replace `vector_search.search()` with the pgvector cosine operator:

```python
# search (top-k by cosine similarity, filtered by corpus):
rows = conn.execute(
    "SELECT id, corpus, content, metadata, "
    "1 - (embedding <=> %s::vector) AS score "
    "FROM documents WHERE corpus = %s "
    "ORDER BY embedding <=> %s::vector LIMIT %s",
    (embedding, corpus, embedding, top_k)
).fetchall()
```

The `EmbeddingDimensionMismatchError` behavior is now implicit in the pgvector operator itself (it will raise a dimension mismatch error on a bad query vector) — keep the exception class and re-raise it wrapping the pgvector error, so existing test mocks and the `retriever` node's non-catching behavior are preserved.

The `retriever` node accepts an optional `store` argument for tests; when it's `None` it reads from a module-level default. That default should become a lazy `get_document_store()` factory returning a real psycopg connection, following the same gateway-factory pattern as `get_chat_client`.

### 1.6 Cross-encoder reranker (`src/reranking/cross_encoder.py`)

Replace `_CrossEncoder.predict()` with the real model:

```python
from sentence_transformers import CrossEncoder

def get_reranker_model(model_name: str = "BAAI/bge-reranker-base") -> CrossEncoder:
    return CrossEncoder(model_name)
```

Delete `_CrossEncoder`. The `predict(pairs)` interface is identical to `sentence_transformers.CrossEncoder.predict()`, so the `reranker` node is unchanged. The model is downloaded from HuggingFace on first call (~1 GB); cache it at `~/.cache/huggingface/` or set `SENTENCE_TRANSFORMERS_HOME` to a persistent volume.

### 1.7 Fine-tuned embedding model (`src/embeddings/finetuned_embeddings.py`)

Replace `_LocalEmbeddingModel.embed_documents()` with the real sentence-transformers model:

```python
from sentence_transformers import SentenceTransformer

def get_finetuned_embedding_model(model_path: str = DEFAULT_MODEL_PATH) -> SentenceTransformer:
    return SentenceTransformer(model_path)
```

`DEFAULT_MODEL_PATH = "models/finetuned-embeddings/v1"` — this directory won't exist until `make eval` (or `scripts/finetune_embedding_model.py`) has run and promoted a model. The `retriever` node only reaches this path when `EMBEDDING_MODEL_VARIANT=finetuned`, so it fails at runtime rather than startup if the path is absent — which is correct. Run `scripts/finetune_embedding_model.py` and the A/B gate before enabling this variant in production.

### 1.8 Staging API client (`src/tools/executors.py`)

Replace `_StagingApiClient.call()` with a real `httpx` call:

```python
import httpx

@dataclass
class _StagingApiClient:
    base_url: str = "http://mock-staging-api"

    def call(self, tool: str, args: dict) -> dict:
        response = httpx.post(
            f"{self.base_url}/execute",
            json={"tool": tool, "args": args},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
```

The `mock-staging-api` service is referenced in the code but **not yet declared in `infra/docker-compose.yml`**. Add it — a minimal FastAPI app (or even a Flask stub) that accepts `POST /execute` with `{tool, args}` and returns `{success, output, error}`. The service doesn't need to touch real production systems; its purpose is to be a realistic async boundary for the execute node that the test suite can run against. The tool registry (`src/tools/registry.py`) defines which tools exist; the staging API just needs to handle them without real side effects.

### 1.9 LangSmith registry + finetuning modules

- **`src/evals/langsmith_registry.py`**: replace the `_EvaluatorRegistry` singleton with `langsmith.Client()`. The only surface used is `register_evaluator`/`get_evaluator` — map these to `client.push_evaluator()`/`client.pull_evaluator()` or adapt to the current LangSmith SDK's evaluator API.

- **`src/finetuning/langsmith_spans.py`**: replace the `NotImplementedError` stub with real LangSmith span export via `langsmith.Client().list_runs(...)`.

- **`src/finetuning/ab_eval.py`**: replace the stub `compute_context_precision()` with a real `ragas` call. The promotion gate logic (comparing against a stored baseline, `PROMOTION_MARGIN`) is already correct — only the metric computation is stubbed.

These three are lower urgency than 1.2–1.8 because they're only called from `make eval` and the fine-tuning scripts, not from the main graph path.

---

## Phase 2 — Build the HTTP API (Open Question #10)

FastAPI is already in `requirements.txt`. The API needs exactly two endpoints; all the contracts are already designed.

**File: `src/api/app.py`**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg, os
from langgraph.checkpoint.postgres import PostgresSaver
from src.graph.build import build_graph
from src.graph.state import HumanDecision, IncidentState

graph = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()
    graph = build_graph(checkpointer=checkpointer)
    yield
    conn.close()

app = FastAPI(lifespan=lifespan)
```

**`POST /runs`** — starts a new run and returns immediately. For a `side_effecting` proposed action, the run will pause at `await_human_approval` and the response will include `status: "awaiting_approval"`.

```python
class StartRunRequest(BaseModel):
    raw_alert: str
    thread_id: str        # caller-supplied; use a UUID

@app.post("/runs")
def start_run(req: StartRunRequest):
    initial_state: IncidentState = {
        "raw_alert": req.raw_alert,
        "thread_id": req.thread_id,
        "retrieved_docs": [], "reranked_docs": [],
        "retry_count": 0,
        # all Optional fields default to None
    }
    config = {"configurable": {"thread_id": req.thread_id}}
    result = graph.invoke(initial_state, config=config)
    paused = "__interrupt__" in result
    return {
        "thread_id": req.thread_id,
        "status": "awaiting_approval" if paused else "complete",
        "proposed_action": result.get("proposed_action"),
        "result": result if not paused else None,
    }
```

**`POST /runs/{thread_id}/approve`** — writes the human decision into the paused checkpoint, then resumes:

```python
class ApprovalRequest(BaseModel):
    approved: bool
    modified_action: dict | None = None
    note: str = ""

@app.post("/runs/{thread_id}/approve")
def submit_approval(thread_id: str, req: ApprovalRequest):
    config = {"configurable": {"thread_id": thread_id}}
    graph.update_state(config, {"human_decision": HumanDecision(
        approved=req.approved,
        modified_action=req.modified_action,
        note=req.note,
    )})
    result = graph.invoke(None, config=config)
    return {"thread_id": thread_id, "status": "complete", "result": result}
```

Wire startup into `scripts/entrypoint.sh` under a new `serve` case:
```bash
serve) exec uvicorn src.api.app:app --host 0.0.0.0 --port 8000 ;;
```

And update the `app` service's `command` in `infra/docker-compose.yml` from `"smoke"` to `"serve"`, and add `ports: ["8000:8000"]`.

**What to add later:** `GET /runs/{thread_id}` (inspect current state), auth middleware, proper error handling for `CheckpointNotFoundError` (thread_id not found → 404).

---

## Phase 3 — Boot Real Infrastructure

### 3.1 Credentials

```bash
cp infra/.env.example infra/.env
```

Fill in:
- `OPENAI_API_KEY` — primary chat + embedding models
- `TOGETHERAI_API_KEY` — `sentinel-guardrail` (Llama Guard via Together AI)
- `LITELLM_PROXY_URL=http://localhost:4000` (host-side; inside Docker it's `http://litellm:4000`)
- `LITELLM_VIRTUAL_KEY` — one of `sentinel-app`, `sentinel-eval`, `sentinel-dev` from `litellm_config.yaml`
- `LANGCHAIN_API_KEY` — for LangSmith tracing
- `OLLAMA_BASE_URL=http://ollama:11434` (inside Docker)

Run `make check-env` to validate before proceeding.

### 3.2 Start infra

```bash
make up                 # Postgres + Redis + LiteLLM proxy + Ollama
make pull-local-models  # ~14 GB; pulls llama3.1:8b-instruct + bge-m3 into Ollama
```

`pull-local-models` only needs to run once; models are persisted in the `ollama_models` Docker volume.

### 3.3 Initialize Postgres

The pgvector extension and `documents` table (Phase 1.5's SQL) need to be created once:

```bash
make shell-db
# inside psql:
CREATE EXTENSION IF NOT EXISTS vector;
# then run the CREATE TABLE / CREATE INDEX from Phase 1.5
```

If you added a proper DB migration tool (recommended), run migrations here instead.

### 3.4 Ingest corpora

```bash
make ingest
```

This calls `scripts/ingest_corpora.py`, which embeds `corpora/runbooks/*.md`, `corpora/postmortems/*.md`, and `corpora/infra_code_docs/*.md` via `sentinel-embedding` and writes rows to the `documents` table. Re-running is idempotent (content-hash keyed upsert). **Must be re-run** any time the primary embedding model is swapped — see `docs/SWAPPING_MODELS.md`.

### 3.5 Run the full Docker test suite

```bash
make test
```

This runs `pytest` inside the app container against real `langgraph`, `langchain-openai`, etc. — the first time the full suite runs against real packages rather than shims. Expect integration tests (marked `@pytest.mark.integration` and skipped by `make test-local`) to run here.

### 3.6 Smoke check + start

```bash
make smoke   # confirms graph builds and gateway wires correctly end-to-end
# Then start the API:
docker compose -f infra/docker-compose.yml up app
```

Test the live system:
```bash
# Start a run:
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"raw_alert": "disk usage above 95% on db-primary", "thread_id": "test-001"}'

# If it returns status=awaiting_approval, submit a decision:
curl -X POST http://localhost:8000/runs/test-001/approve \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "note": "proceed"}'
```

---

## Deferred but do before real traffic

These don't block the first real run but should be resolved before treating the system as production-ready:

- **Execute retry cap** (Open Question #11): add a `execute_retry_count` field to `IncidentState` and a cap in `build.py`'s `execute_route`, mirroring `grade_documents`' `retry_count` pattern exactly.
- **`diagnose` re-entry context** (Open Question #9): the `diagnose` prompt doesn't currently differentiate first-pass from re-entry on human rejection or execution failure. Needs prompt engineering before the re-entry paths are exercised with real traffic.
- **Rate-limit/budget caps** (Open Question #12): `infra/litellm_config.yaml`'s virtual-key `rpm_limit` and `max_budget` values are placeholders — set real numbers once you have a baseline from `make eval`.
- **Add the mock-staging-api service** to `docker-compose.yml` (required for Phase 1.8 to work end-to-end in Docker, not just in unit tests).
