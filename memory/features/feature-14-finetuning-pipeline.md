# Feature 14 — Fine-Tuning Pipeline (Final Roadmap Item)

**Phase introduced:** Phase 4
**Status:** In Progress (design complete; implementation/tests pending)
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
