# Feature 05 — `retriever` + `reranker` Nodes

**Phase introduced:** Phase 4
**Status:** In Progress (design complete; implementation/tests pending)
**PMA sections touched:** ADR-011 (new), §3 Pillar 1, §3 Pillar 4, §6 Feature Log, §9 item 5

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
