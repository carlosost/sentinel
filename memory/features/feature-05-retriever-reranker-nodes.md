# Feature 05 — `retriever` + `reranker` Nodes

**Phase introduced:** Phase 4
**Status:** Done — implemented and tested (against sandbox shims; see Implementation Status below)
**PMA sections touched:** ADR-011 (new), ADR-021 (addendum), §3 Pillar 1, §3 Pillar 4, §6 Feature Log, §7 (Open Question #15 addendum), §9 item 5

## Feature Description

Add the `retriever` and `reranker` nodes: pgvector similarity search at top-k=20
against the corpus selected by `router`, followed by `bge-reranker-base` cross-encoder
re-ranking down to top-k=5.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — both nodes follow the skeleton's existing positions. |
| ADR-002 (Postgres checkpointer) | No conflict — `retriever` queries the `documents` table on the same Postgres instance; no interrupt involved. |
| ADR-003 (Gateway for every LLM/embedding client) | No conflict — the retriever's query-embedding call goes through `client_factory.get_embedding_client(...)`. The reranker is explicitly **not** a gateway call: `bge-reranker-base` runs locally as a cross-encoder (Pillar 1's original "no extra API dependency" decision from Phase 1), so it falls outside ADR-003's scope by design, not by oversight — called out explicitly here so it isn't later mistaken for a gateway bypass. |
| ADR-004 (Guardrail stub) | No conflict — unrelated surface. |
| ADR-005 (Eval strategy) | No conflict — this is the feature that finally gives ragas `context_precision`/`context_recall` real input to score, resolving the long-standing caveat from Features 02 and 04. |
| ADR-006 (Lint) | No conflict — no new gateway-bypassing client construction; the local `CrossEncoder` import doesn't match the lint's `openai`/`anthropic`/direct-`ChatOpenAI` pattern. |
| ADR-007 (Scaffolding) | No conflict — node files added at `src/graph/nodes/retriever.py` and `src/graph/nodes/reranker.py`, per the convention ADR-009 already established. |
| ADR-008 (Eval harness) | No conflict — `make eval` can now run meaningfully against real retrieval output; the first ragas baseline becomes recordable once this feature's code lands (not yet, at design stage). |
| ADR-009 (Skeleton retrofit) | No conflict — retriever/reranker positions unaffected by the guardrail rejection-branch fix. |
| ADR-010 (Router scope) | No conflict — `retriever` reads `state.route` as a single corpus value, exactly as ADR-010 decided. |
| §5.1 IncidentState schema | No conflict on existing keys (`retrieved_docs: list[dict]`, `reranked_docs: list[dict]` already declared) — but neither dict's internal shape was ever pinned. This is a gap, not a contradiction; filled in additively below. |
| §5.2 Graph skeleton | No conflict — `router -> retriever -> reranker -> grade_documents` matches exactly. |
| §5.3 Gateway contract | No conflict, same note as ADR-003. |

**Verdict: ADDITIVE.** No existing ADR or contract is contradicted; the document-dict
shape was an unfilled gap, not a disputed decision.

## New ADR

### ADR-011: Retrieved/reranked document shape; reranker confirmed as a local, non-gateway model
- **Context:** §5.1 declared `retrieved_docs`/`reranked_docs` as `list[dict]` without
  pinning the dict's fields, and it was never explicit that the reranker is
  intentionally outside the gateway contract.
- **Decision:**
  - **Document dict shape**, used by both `retrieved_docs` and `reranked_docs`:
    ```python
    {
        "id": str,
        "corpus": str,            # "runbooks" | "postmortems" | "infra_code_docs"
        "content": str,
        "source": str,            # e.g. file path / doc identifier
        "score": float,           # vector similarity score (retrieved_docs)
                                   # or cross-encoder score (reranked_docs)
    }
    ```
    `reranked_docs` entries carry the cross-encoder `score`, overwriting the vector
    score field rather than adding a second one — only one ranking is authoritative
    at a time, avoiding ambiguity about which score `grade_documents` should read.
  - **Retriever:** pgvector cosine-similarity query against `documents` filtered by
    `corpus = state.route`, `LIMIT 20`, query embedded via
    `client_factory.get_embedding_client(...)`.
  - **Reranker:** `bge-reranker-base` (sentence-transformers `CrossEncoder`), loaded
    and run in-process — confirmed as outside ADR-003's gateway contract by design,
    not an oversight. Scores all 20 candidates, returns the top 5 by descending score.
  - Node files: `src/graph/nodes/retriever.py`, `src/graph/nodes/reranker.py`.
- **Consequences:** Any future node reading `retrieved_docs`/`reranked_docs` can rely
  on this exact shape; adding/renaming a field later is a retrofit against this ADR.
- **Status:** Accepted.

## Forward Note (added by Feature 06)

When `retriever` is actually implemented, its embedding call must encode
`state.current_query` (falling back to `state.raw_alert` if unset), not `raw_alert`
directly — see ADR-012. Neither this file's Gherkin nor its PyTest skeletons asserted
the query source, so nothing above is invalidated by this.

## Implementation Status (real code/tests, sandbox-constrained)

### Implemented
- `src/retrieval/vector_search.py` — plain-Python `cosine_similarity` + `search(store, corpus, query_embedding, k=20)`, the cosine-similarity decision `document_store.py`'s Feature 04 docstring explicitly deferred to this feature. O(n) per query, no index — a stand-in for pgvector's `<=>` operator, not a faithful reproduction.
- `src/ingestion/document_store.py` — added a process-wide `default_store` singleton (the in-sandbox stand-in for "the one Postgres table every node talks to"); `scripts/ingest_corpora.py` and tests still use their own fresh `InMemoryDocumentStore()` instances, never this singleton.
- `src/reranking/cross_encoder.py` — `_CrossEncoder`/`get_reranker_model()` stand-in for `sentence_transformers.CrossEncoder("BAAI/bge-reranker-base")`; `.predict()` raises `NotImplementedError`, mirroring `client_factory`'s stub clients. Has zero dependency on `src.gateway`, preserving ADR-011's gateway-exclusion boundary by construction, not just by convention.
- `src/graph/nodes/retriever.py` — real node: reads `state.route` (raises `RetrieverError` if unset — never defaults to a corpus), embeds `state.raw_alert` via `client_factory.get_embedding_client(...)`, calls `vector_search.search` against the routed corpus, returns `retrieved_docs` in the ADR-011 dict shape. Accepts an optional `store=` kwarg for test injection; defaults to `document_store.default_store`.
- `src/graph/nodes/reranker.py` — real node: short-circuits to `{"reranked_docs": []}` on empty input (untested edge case the original Gherkin/PyTest skeleton didn't enumerate, added defensively); otherwise scores all candidates via the cross-encoder stand-in, overwrites `score`, sorts descending, returns top 5. Never imports `client_factory`.
- `src/graph/build.py` — `router -> retriever -> reranker -> grade_documents(placeholder)`; `_retriever_placeholder` removed, replaced by `_grade_documents_placeholder` (roadmap item 6 / Feature 06).
- `tests/retrieval/test_vector_search.py` (10 tests), `tests/reranking/test_cross_encoder.py` (2 tests), `tests/graph/nodes/test_retriever.py` (4 tests), `tests/graph/nodes/test_reranker.py` (4 tests) — all Deterministic Tier.
- `tests/graph/test_skeleton.py` — safe-path test extended through `retriever`/`reranker` with the embedding client mocked; asserts the default empty store yields `retrieved_docs == [] ` and `reranked_docs == []`.

### Deviations from the original Gherkin/PyTest skeleton
- Skeleton didn't specify retriever's failure mode when `state.route` is unset; added `RetrieverError` (same hard-fail discipline as `RouterError`) plus a dedicated test, not in the original enumeration.
- Skeleton didn't specify reranker's behavior on empty `retrieved_docs`; added an explicit short-circuit (returns `[]` without touching the cross-encoder) plus a dedicated test.
- `vector_search.py` and the `document_store.default_store` singleton are net-new modules/decisions, not just node implementations — both are additive consequences of Feature 04's explicit "Feature 05 will need its own decision" deferral, not scope creep.

### Verification performed
- `python3 -m unittest discover -s tests` → **74/74 passing** (up from 54; +20 new: 10 vector_search, 2 cross_encoder shim, 4 retriever, 4 reranker; `test_skeleton.py`'s safe-path test extended rather than added).
- `bash scripts/lint_gateway_usage.sh` → passed (reranker's local cross-encoder import correctly does not trip the gateway-bypass lint).
- `python3 scripts/run_eval.py` → passed (harness mechanics only; no ragas baseline yet — still gated on `diagnose`/`propose_action`, roadmap item 7).

### Definition of Done checklist
- [x] Gherkin scenarios from this spec have corresponding passing tests (corpus filter, top-k=20 cap, gateway-routed embedding call; top-5 descending rerank, score overwrite, gateway-isolation).
- [x] Deterministic Tier fully mocked, no live infra/API keys.
- [x] PROJECT_MEMORY.md updated (Feature Log, ADR-021 addendum, §9 checkbox).
- [ ] Probabilistic Tier (ragas `context_precision`/`context_recall` baseline) — not yet applicable; needs `diagnose`/`propose_action` (Feature 07) before `make eval` has a full pipeline to score.
- [ ] Real-package parity (Open Question #15: real pgvector query, real `sentence-transformers` cross-encoder) — not yet verified; tracked, not blocking.

## Blast Radius

Additive — no existing ADR superseded, no existing test/spec files broken.

## Pillar Impact

- [x] 1. Advanced RAG Mechanics — retrieval (top-k=20) and re-ranking (top-k=5)
      mechanics implemented; `grade_documents`/self-RAG retry remains roadmap item 6.
- [x] 4. LLM Evals — the eval harness (ADR-008) now has real retrieval output to
      score; the first ragas `context_precision`/`context_recall` baseline is recorded
      once this feature's code lands and `make eval` runs against it — not claimed as
      already measured at this design stage.
- [ ] 2, 3, 5, 6 — not touched.

## Gherkin

```gherkin
Feature: retriever fetches top-k=20 candidates from the routed corpus

  Scenario: retriever queries only the routed corpus
    Given state.route is "runbooks"
    And the documents table has rows for "runbooks", "postmortems", and "infra_code_docs"
    When the retriever node runs
    Then exactly 20 candidates are returned (or fewer if the corpus has <20 rows)
    And every candidate's corpus field equals "runbooks"
    And every candidate has content, source, and score fields

  Scenario: retriever's query embedding goes through the gateway
    Given a mocked client_factory
    When the retriever node runs
    Then client_factory.get_embedding_client is called, not a direct provider SDK

Feature: reranker reduces 20 candidates to the top 5 by cross-encoder score

  Scenario: reranker returns exactly 5 documents sorted by descending score
    Given 20 retrieved_docs with mocked cross-encoder scores
    When the reranker node runs
    Then reranked_docs has exactly 5 entries
    And reranked_docs is sorted by score descending
    And each entry's score is the cross-encoder score, not the original vector score

  Scenario: reranker does not call the gateway
    Given a mocked client_factory
    When the reranker node runs
    Then client_factory.get_chat_client and client_factory.get_embedding_client are
      never called
```

## PyTest Skeletons (all Deterministic Tier — retrieval/rerank mechanics, mocked pgvector and mocked CrossEncoder; relevance/groundedness quality is Probabilistic Tier per §8.2 and is NOT asserted here)

```python
# tests/graph/nodes/test_retriever.py

def test_retriever_filters_by_routed_corpus(mock_pgvector, mock_embedding_client):
    """Deterministic Tier. Asserts corpus filter and top-k=20 cap, not which docs are
    'relevant'."""
    ...

def test_retriever_uses_client_factory_for_embedding(mock_client_factory):
    """Deterministic Tier. Enforces ADR-003/006 on the retriever's embedding call."""
    ...


# tests/graph/nodes/test_reranker.py

def test_reranker_returns_top_5_by_descending_score(mock_cross_encoder):
    """Deterministic Tier. Mocks CrossEncoder.predict to return fixed scores; asserts
    count, order, and field overwrite — never asserts the *correctness* of the
    ranking."""
    ...

def test_reranker_never_calls_gateway(mock_client_factory):
    """Deterministic Tier. Asserts the local reranker path makes zero calls to
    client_factory, confirming the ADR-011 scope boundary."""
    ...
```
