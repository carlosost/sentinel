# Feature 14 — Fine-Tuning Pipeline (Final Roadmap Item)

**Phase introduced:** Phase 4
**Status:** Done
**PMA sections touched:** ADR-020 (new, retrofit), §3 Pillar 6, §3 Pillar 1, §7
(resolves Open Question #5, new Open Question), §6 Feature Log, §9 item 14

## Feature Description

Build the fine-tuning pipeline: `scripts/export_finetune_pairs.py` exporting
`grade_documents` LangSmith traces into contrastive JSONL pairs, a
`sentence-transformers` fine-tune of `bge-small-en-v1.5`, and an A/B eval against the
golden set before promoting it behind a config flag.

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001, ADR-002 | No conflict — no graph/checkpointer surface touched. |
| ADR-003 (Gateway) | No conflict, but a scope decision is needed: does the fine-tuned embedding model run through the gateway or locally? Resolved below — same precedent as the reranker (ADR-011) and tool execution (ADR-016): runs locally in-process, confirmed a **third time** as outside ADR-003's scope by design. |
| ADR-005, ADR-008 (Eval strategy/harness) | No conflict — the A/B eval reuses `ragas context_precision`/`context_recall` against the existing golden set and reference docs; no new dataset or schema needed. |
| ADR-006 (Lint) | No conflict — loading a local fine-tuned `sentence-transformers` model is not an LLM/embedding *client* construction, same as the reranker; the lint rule is unaffected. |
| ADR-010 (Router scope) | No conflict — fine-tuning targets retrieval ranking quality and (per the original Pillar 6 prose) router classification; this feature only implements the retrieval side, the router side remains future scope, noted not expanded here. |
| ADR-011 (Document shape, reranker) | No conflict — and this is the key resolution: `reranked_docs[].score` (the cross-encoder score, already real per ADR-011) is a genuine per-document relevance signal that already exists, independent of `grade_documents`. |
| **§3 Pillar 6 prose (original Phase 1 draft)** | **Conflict found:** Pillar 6's data-source description says contrastive pairs come from "LangSmith traces of the `grade_documents` node — every (query, retrieved_doc, relevance_grade) triple." But ADR-012 (Feature 06) defined `grade_documents` as emitting one **aggregate** `relevance_grade: float` for the whole batch of `reranked_docs`, not a per-document grade. There is no per-document grade to export from `grade_documents` traces as originally described. Resolved below by using the per-document signal that actually exists. |
| ADR-012 (Self-RAG mechanics) | No conflict — this feature does not modify `grade_documents` or its aggregate-grade contract; the data-source correction routes around it instead of retrofitting it. |
| ADR-013 through ADR-019 | No conflict — unrelated surfaces. |
| §5.1 IncidentState schema | No conflict — no new field needed; the embedding-model variant is a deployment-level config flag, not per-run state. |
| §5.2 Graph skeleton | No conflict — `retriever`'s position is unchanged; only its internal embedding call gains a second code path. |
| §5.3 Gateway contract | No conflict, same note as ADR-003. |
| **Open Question #5 (promotion criteria)** | Not a conflict, but the explicit thing this feature must resolve per its own description. Resolved below. |

**Verdict: RETROFIT** — corrects Pillar 6's prose claim about the fine-tuning data
source (which named a per-document signal that was never actually implemented in
`grade_documents`) to point at the per-document signal that does exist
(`reranked_docs[].score`, ADR-011). No previously-built code or test depended on the
incorrect description, since this is the first feature to implement Pillar 6 at all.

## New ADR (Retrofit)

### ADR-020: Fine-tuning data source correction; promotion criteria; local model-swap scope (resolves Open Question #5)
- **Context:** Pillar 6's original prose named `grade_documents`' per-(query, doc)
  relevance grade as the contrastive-pair data source, but ADR-012 only ever defined
  an aggregate grade for the whole retrieved batch — there was nothing per-document to
  export as described. Additionally, "outperforms base on golden set" (Project
  Charter success criterion 5 / Open Question #5) had no numeric promotion threshold.
- **Decision:**
  - **Corrected data source:** `scripts/export_finetune_pairs.py` exports from
    LangSmith **retriever + reranker spans**, not `grade_documents` spans. For each
    query: positive examples are the top-`k` `reranked_docs` (by `score`), negative
    examples are `retrieved_docs` entries that did **not** survive re-ranking into the
    top-5 — both already carry the document shape ADR-011 pinned. Output:
    `evals/finetune_pairs.jsonl`, one `{"query": str, "positive": dict, "negative": dict}`
    record per pair.
  - **Fine-tune mechanics:** `scripts/finetune_embedding_model.py` runs a
    `sentence-transformers` contrastive fine-tune (`MultipleNegativesRankingLoss`) of
    `BAAI/bge-small-en-v1.5` on the exported pairs, writing a versioned artifact to
    `models/finetuned-embeddings/v{N}/`.
  - **A/B eval & promotion criteria (resolves Open Question #5):**
    `scripts/ab_eval_embedding_model.py` runs `ragas context_precision`/
    `context_recall` against `evals/golden_incidents.jsonl` once with the base
    embedding model and once with the candidate fine-tuned model. **Promotion rule:**
    the candidate is promoted only if it improves `context_precision` by at least a
    configured margin (placeholder value pending real measurement — new Open
    Question) over the currently-promoted model's last recorded baseline, recorded
    as a new baseline in the Feature Log (§6) per §8.5 item 4, not just observed and
    discarded.
  - **Config flag, local execution:** the promoted variant is selected via an
    `EMBEDDING_MODEL_VARIANT=base|finetuned` deployment config read by
    `src/graph/nodes/retriever.py`. When set to `finetuned`, the retriever loads the
    versioned local model artifact directly (`sentence-transformers`, in-process) —
    confirmed outside ADR-003's gateway scope, the same precedent as the reranker
    (ADR-011) and tool execution (ADR-016). When `base`, retrieval is unchanged
    (`client_factory.get_embedding_client(...)`, through the gateway).
  - **Out of scope, deferred:** fine-tuning `router`'s classification (also named in
    Pillar 6's original prose) is not built here — only the retrieval-embedding side.
    Using `human_decision.note`'s free text as a *structured* "retrieval was wrong"
    signal is also not built — `note` remains unstructured per ADR-015 and is not
    parsed for this pipeline.
- **Consequences:** Resolves Open Question #5 with a concrete mechanism (A/B against
  a recorded baseline, gated by a margin). The margin's specific numeric value is a
  new placeholder (Open Question), same pattern as ADR-012's relevance threshold and
  ADR-018/019's caps. Pillar 6's prose now accurately describes where contrastive
  pairs actually come from.
- **Status:** Accepted.

## Blast Radius

- **Pillar 6 prose corrected** (data source: `grade_documents` → retriever/reranker
  spans) — no prior feature implemented Pillar 6, so nothing built against the
  incorrect description breaks.
- **Open Question #5 resolved** — marked `Resolved by ADR-020` in §7, not deleted.
- No existing ADR is superseded; `grade_documents` (ADR-012) is unchanged.
- **New Open Question flagged:** the promotion margin (how much `context_precision`
  improvement is required to promote) is a placeholder with no empirical basis yet.

## Pillar Impact

- [x] 6. Fine-Tuning Integration — first implementation of this pillar: export
      pipeline, fine-tune script, A/B promotion mechanism, and config-flag swap are
      now fully specified. Confirms the third instance of the local/non-gateway model
      precedent.
- [x] 1. Advanced RAG Mechanics — `retriever`'s embedding call gains a second,
      swappable code path (base vs. fine-tuned); the document shape it produces
      (ADR-011) is unchanged either way, so downstream nodes are unaffected.
- [ ] 2, 3, 4, 5 — not touched.

## Gherkin

```gherkin
Feature: fine-tuning pipeline exports pairs, trains, and conditionally promotes

  Scenario: contrastive pairs are exported from retriever/reranker spans, not grade_documents
    Given mocked LangSmith retriever and reranker spans for several queries
    When export_finetune_pairs.py runs
    Then evals/finetune_pairs.jsonl contains one positive/negative pair per query
    And no field is read from a grade_documents span

  Scenario: a candidate model that beats the baseline by the margin is promoted
    Given the candidate's context_precision exceeds the recorded baseline by at least
      the configured margin
    When ab_eval_embedding_model.py runs
    Then the candidate is marked promoted
    And a new baseline is recorded in the Feature Log

  Scenario: a candidate model that does not beat the margin is not promoted
    Given the candidate's context_precision improvement is below the configured margin
    When ab_eval_embedding_model.py runs
    Then the candidate is marked not promoted
    And EMBEDDING_MODEL_VARIANT remains "base"

  Scenario: retriever loads the fine-tuned model locally, not through the gateway
    Given EMBEDDING_MODEL_VARIANT=finetuned
    And a mocked client_factory
    When the retriever node runs
    Then client_factory.get_embedding_client is never called
    And the local sentence-transformers model is used instead

  Scenario: retriever falls back to the gateway-routed base model when unset
    Given EMBEDDING_MODEL_VARIANT=base
    When the retriever node runs
    Then client_factory.get_embedding_client is called as before
```

## PyTest Skeletons (Deterministic Tier for pipeline mechanics/config-flag routing per §8.2's Pillar 6 row "export pipeline shape/correctness"; the model-performance delta itself is Probabilistic Tier, scored by ab_eval_embedding_model.py, never asserted with `==`)

```python
# tests/finetuning/test_export_finetune_pairs.py

def test_pairs_exported_from_retriever_reranker_spans_not_grade_documents(mock_langsmith_client):
    """Deterministic Tier. Enforces ADR-020's corrected data source."""
    ...

def test_positive_examples_are_top_k_reranked_docs(mock_langsmith_client):
    """Deterministic Tier."""
    ...


# tests/finetuning/test_ab_eval_embedding_model.py

def test_candidate_above_margin_is_promoted(mock_ragas_scores):
    """Deterministic Tier. Asserts the promotion *decision* given mocked scores —
    not whether ragas's scores themselves are correct."""
    ...

def test_candidate_below_margin_is_not_promoted(mock_ragas_scores):
    """Deterministic Tier."""
    ...


# tests/graph/nodes/test_retriever_model_variant.py

def test_finetuned_variant_skips_gateway_embedding_client(mock_client_factory, mock_local_model):
    """Deterministic Tier. Enforces the ADR-011/016/020 local-model gateway-scope
    precedent for the third time."""
    ...

def test_base_variant_uses_gateway_embedding_client(mock_client_factory):
    """Deterministic Tier."""
    ...
```

## Implementation Status

**What was built:**
- `src/finetuning/export_pairs.py` — `build_finetune_pairs(spans)`, pure: one
  `{"query", "positive", "negative"}` pair per span, `positive` = `reranked_docs[0]`
  (already sorted descending by the reranker node, ADR-011), `negative` = the first
  `retrieved_docs` entry whose `id` did not survive into `reranked_docs`. Raises
  `ExportPairsError` (never silently skips) on a missing query, no reranked_docs, or
  no negative candidate available.
- `src/finetuning/langsmith_spans.py` — `get_retriever_reranker_spans()`, the
  ADR-021-pattern stand-in for a real `langsmith.Client()` spans fetch; raises
  `NotImplementedError` (Open Question #15), the same seam tests patch directly.
- `src/finetuning/ab_eval.py` — `decide_promotion(baseline, candidate, margin=
  PROMOTION_MARGIN)` (pure, Deterministic Tier) and `run_ab_eval(golden_incidents)`,
  which calls `_score_variant("base"/"finetuned", ...)` (a `NotImplementedError`
  stand-in for real `ragas` scoring) and feeds both scores to `decide_promotion`.
  `PROMOTION_MARGIN = 0.05` is the placeholder value Open Question #14 already
  tracks.
- `src/embeddings/finetuned_embeddings.py` — `get_finetuned_embedding_model()`,
  mirroring `cross_encoder.py`'s `_CrossEncoder` shim exactly: no dependency on
  `src.gateway.client_factory` at all, `.embed_documents()` raises
  `NotImplementedError` until Open Question #15's real-package swap.
- `src/graph/nodes/retriever.py` — gained the `EMBEDDING_MODEL_VARIANT` env-var
  branch: `"finetuned"` calls `get_finetuned_embedding_model()` instead of
  `client_factory.get_embedding_client(...)`; unset/`"base"` is unchanged. Both paths
  produce the same `retrieved_docs` shape (ADR-011), so no downstream node changed.
- Three new entry-point scripts mirroring `scripts/run_eval.py`'s mechanics-only
  pattern given this sandbox's lack of `langsmith`/`sentence-transformers`/`ragas`
  package access (Open Question #15): `scripts/export_finetune_pairs.py`,
  `scripts/finetune_embedding_model.py`, `scripts/ab_eval_embedding_model.py` — each
  validates what it can (script wiring, file presence, dataset schema) and reports
  the sandbox limitation explicitly rather than silently no-op'ing.
- New tests: `tests/finetuning/test_export_finetune_pairs.py` (7 tests),
  `tests/finetuning/test_ab_eval_embedding_model.py` (8 tests),
  `tests/finetuning/test_langsmith_spans.py` (1 test),
  `tests/embeddings/test_finetuned_embeddings.py` (3 tests),
  `tests/graph/nodes/test_retriever_model_variant.py` (3 tests, matching both named
  spec skeletons plus an unset-defaults-to-base regression test).

**Deviations from spec:**
- The spec's named skeleton file was `tests/finetuning/test_export_finetune_pairs.py`
  with `mock_langsmith_client`-fixture-style tests; the actual implementation tests
  `build_finetune_pairs` directly against synthetic span dicts (no client mock
  needed, since `build_finetune_pairs` is a pure function over already-fetched
  spans) and separately covers `get_retriever_reranker_spans`'s own shim contract in
  `test_langsmith_spans.py`. Same coverage intent, split along the same module
  boundary the implementation actually has.
- `scripts/finetune_embedding_model.py`'s `main()` exits 1 when
  `evals/finetune_pairs.jsonl` doesn't exist yet (expected in this sandbox, since
  `export_finetune_pairs.py` cannot produce a real file without `langsmith`) — this
  is correct mechanics-validation behavior, not a bug; running the three scripts in
  sequence in a sandbox with real package access would produce a real pairs file
  before this script runs.

**New Open Question confirmed, not invented:** Open Question #14 in §7 (fine-tuned
model promotion margin is a placeholder) was already pre-flagged in the PMA before
this feature started — no new Open Question number was added, consistent with the
Feature 11/12/13 pattern.

**Verification:**
- `python -m unittest discover -s tests -p "test_*.py"` → 190/190 passing (up from
  168).
- `bash scripts/lint_gateway_usage.sh` → PASS.
- `python scripts/export_finetune_pairs.py` → reports the sandbox limitation
  (Open Question #15), exits 0.
- `python scripts/finetune_embedding_model.py` → exits 1 (no pairs file — expected,
  see Deviations above).
- `python scripts/ab_eval_embedding_model.py` → loads the golden dataset, reports
  the sandbox limitation, exits 0.
- `python scripts/run_eval.py` → unaffected, still PASS.

**Definition of Done:**
- [x] Spec's Conflict Check verified still holds (no re-derivation needed).
- [x] Implementation matches ADR-020 (corrected data source, promotion margin
      mechanism, local in-process model-swap).
- [x] Tests written and passing (Deterministic Tier throughout — pipeline mechanics
      and config-flag routing; real model-performance delta remains Probabilistic
      Tier, gated on Open Question #15).
- [x] Lint green; eval harness unaffected and still green.
- [x] Feature file Status → Done, this section appended.
- [x] docs/PROJECT_MEMORY.md updated (ADR-020 implementation-status bullet, Feature Log
      row, §9 checkbox). Pillar 6/Pillar 1's "Implementation status (Feature 14)"
      bullets and Open Question #5's resolution marker were already pre-drafted
      accurately and required no further correction.
