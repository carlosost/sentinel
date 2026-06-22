# Feature 04 — Corpus Ingestion + `router` Node

**Phase introduced:** Phase 4
**Status:** In Progress (design complete; implementation/tests pending)
**PMA sections touched:** ADR-010 (new, retrofit), §3 Pillar 1, §6 Feature Log, §9 item 4

## Feature Description

Ingest runbooks, postmortems, and infra/code docs into pgvector, then add the `router`
node that classifies the incoming query against those three corpora and selects a
retriever.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 (LangGraph backbone) | No conflict — `router` is exactly the conditional-edge node ADR-001/Pillar 1 call for, not an LCEL `RouterChain`. |
| ADR-002 (Postgres checkpointer) | No conflict — ingestion reuses the same Postgres instance for pgvector, as already decided; no checkpointer interaction at ingestion time. |
| ADR-003 (Gateway) | No conflict, requirement carries forward: the router's classification call and the ingestion script's embedding calls both go through `client_factory`, never a direct provider SDK. |
| ADR-004 (Guardrail stub) | No conflict — `router` only runs after `guardrail_input` per the skeleton; out of scope here. |
| ADR-005 (Eval strategy) | No conflict — router *accuracy* is already anticipated as Probabilistic Tier in §8.2's pillar mapping table; this feature only builds the *mechanism*. |
| ADR-006 (Lint) | No conflict. |
| ADR-007 (Repo scaffolding) | No conflict, minor gap: ADR-007 didn't name a location for ingestion scripts or corpus source files. Resolved additively in ADR-010 below. |
| ADR-008 (Eval harness) | No conflict. Worth noting: this feature still does **not** give ragas's `context_precision`/`context_recall` anything to score — `router` only selects a corpus, it doesn't retrieve documents (that's roadmap item 5). Pillar 4's "no baseline yet" caveat from Feature 02 still holds. |
| ADR-009 (Skeleton retrofit — rejection branches) | No conflict — `router`'s position (`guardrail_input -(safe)-> router -> retriever`) is unchanged by ADR-009. |
| §5.1 IncidentState schema | **Conflict (prose vs. contract).** §3 Pillar 1's prose says the router "selects **one or more** retrievers," but the existing typed contract is `route: Optional[Literal["runbooks", "postmortems", "infra_code_docs"]]` — singular only, not a list. The prose and the contract disagree, and no node has been built against either reading yet. |
| §5.2 Graph skeleton | No conflict — `router -> retriever` is a single edge regardless of which reading of "one or more" is correct; the ambiguity lives in Pillar 1's prose and the field's cardinality, not the skeleton. |
| §5.3 Gateway contract | No conflict, same note as ADR-003. |

**Verdict: RETROFIT** (narrow — Pillar 1 prose is corrected to match the existing
singular `route` contract, rather than expanding the contract to a list; no node or
test currently depends on either reading, so this is caught before it could ship
inconsistently).

## New ADR (Retrofit)

### ADR-010: Router scope is single-corpus per query (v1); corpus ingestion layout
- **Context:** §3 Pillar 1's original prose ("selects one or more retrievers") was
  never reconciled with §5.1's `route` field, which is typed as a single optional
  literal, not a list. Building the router required picking one reading rather than
  leaving the inconsistency to surface later as a confusing bug.
- **Decision:**
  - **Router scope (v1):** `router` classifies each incoming query into **exactly one**
    of `runbooks` | `postmortems` | `infra_code_docs` via a single structured-output
    LLM call through `client_factory.get_chat_client(...)`, and writes it to
    `state.route`. Multi-corpus fan-out (querying more than one corpus per turn) is
    explicitly deferred — tracked as a new Open Question (see below) — not implemented
    as partial/ambiguous behavior.
  - §3 Pillar 1's prose is corrected from "selects one or more retrievers" to "selects
    exactly one retriever corpus per query (v1 simplification)."
  - **Corpus storage:** a single pgvector table `documents(id, corpus, content, embedding, metadata)`
    with `corpus` as a column (`runbooks|postmortems|infra_code_docs`), not three
    separate tables — keeps the downstream `retriever` node (roadmap item 5) a single
    parameterized query rather than three code paths.
  - **Corpus source files:** committed as markdown under `corpora/runbooks/`,
    `corpora/postmortems/`, `corpora/infra_code_docs/` — synthetic sample content,
    consistent with ADR-005's synthetic-data approach for evals.
  - **Ingestion script:** `scripts/ingest_corpora.py`, idempotent (upsert keyed on a
    content hash, so re-running doesn't duplicate rows), embeds via
    `client_factory.get_embedding_client(...)`.
  - **Router node location:** `src/graph/nodes/router.py`, per the `src/graph/nodes/`
    convention established in ADR-009.
- **Consequences:** `route`'s cardinality is now a deliberate, documented decision
  instead of an unresolved ambiguity. If multi-corpus routing is needed later, it is
  itself a retrofit against this ADR (widening `route` to a list and re-justifying
  every node that reads it as singular).
- **Status:** Accepted.

## Forward Note (added by Feature 06)

When `router` is actually implemented, it must classify `state.current_query`
(falling back to `state.raw_alert` if unset), not `state.raw_alert` directly — see
ADR-012. Neither this file's Gherkin nor its PyTest skeletons asserted the query
source, so nothing above is invalidated by this; the implementation should simply not
hardcode `raw_alert`.

## Blast Radius

- **§3 Pillar 1 prose corrected** ("one or more" → "exactly one, v1") to match the
  pre-existing `route` typed contract. No ADR previously asserted the "one or more"
  reading explicitly — it was blueprint prose, now reconciled.
- **No existing test or Gherkin file breaks** — no node has read or written `route` in
  a built node yet (router is the first).
- **New Open Question added:** multi-corpus fan-out is deferred; if a future feature
  needs it, it must retrofit ADR-010, not silently widen `route` to a list.

## Pillar Impact

- [x] 1. Advanced RAG Mechanics — query routing mechanism (first half) implemented:
      classification call + corpus selection. Re-ranking and self-RAG grading remain
      roadmap items 5–6.
- [ ] 2, 3, 4, 5, 6 — not touched (gateway/eval usage here is existing-pattern reuse,
      not a new capability in those pillars).

## Gherkin

```gherkin
Feature: Corpus ingestion populates pgvector with tagged, idempotent rows

  Scenario: ingesting a corpus directory tags every row with its corpus name
    Given the corpora/runbooks/ directory contains 3 markdown files
    When scripts/ingest_corpora.py runs for corpus "runbooks"
    Then 3 rows exist in the documents table with corpus = "runbooks"
    And each row has a non-null embedding vector

  Scenario: re-running ingestion does not duplicate rows
    Given corpus "runbooks" has already been ingested once
    When scripts/ingest_corpora.py runs again for corpus "runbooks" with unchanged files
    Then the row count for corpus "runbooks" is unchanged

Feature: router node classifies a query into exactly one corpus

  Scenario: router writes a single corpus value to state.route
    Given the router's LLM call is mocked to return {"route": "postmortems"}
    And a minimal IncidentState with raw_alert set
    When the router node runs
    Then state.route equals "postmortems"
    And the next edge target is "retriever"

  Scenario: router's LLM call goes through the gateway
    Given a mocked client_factory
    When the router node runs
    Then client_factory.get_chat_client is called, not a direct provider SDK
```

## PyTest Skeletons (all Deterministic Tier — ingestion/routing mechanics, mocked LLM and pgvector; routing *accuracy* is Probabilistic Tier per §8.2 and is NOT asserted here)

```python
# tests/ingestion/test_ingest_corpora.py

def test_ingest_tags_rows_with_corpus_name(mock_pgvector, mock_embedding_client):
    """Deterministic Tier. Asserts row count and corpus tag, not embedding quality."""
    ...

def test_ingest_is_idempotent_on_rerun(mock_pgvector, mock_embedding_client):
    """Deterministic Tier. Asserts no duplicate rows on a second run with unchanged
    source files."""
    ...


# tests/graph/nodes/test_router.py

def test_router_writes_single_route_value(mock_client_factory):
    """Deterministic Tier. client_factory.get_chat_client mocked to return a fixed
    structured classification; asserts state.route and routing target only — never
    asserts whether the classification was the 'correct' corpus for the query."""
    ...

def test_router_uses_client_factory(mock_client_factory):
    """Deterministic Tier. Enforces ADR-003/006 gateway-only construction on the
    router's LLM call."""
    ...
```
