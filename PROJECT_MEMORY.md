# PROJECT MEMORY ASSET (PMA) — v1

> Living architecture record for the project below. Every subsequent phase reads this
> file in full, appends/updates sections in place, and outputs the complete file again.
> Never delete history — superseded decisions are marked `Status: Superseded` and kept,
> not removed.

---

## 1. Project Charter

**Name:** Sentinel — Autonomous SRE Incident Copilot

**Problem statement:** When a production incident fires (alert, error spike, failed
deploy), an on-call engineer must: triage the signal, retrieve relevant context
(runbooks, past postmortems, infra/code docs), diagnose root cause, propose a
remediation, get it approved, execute it, verify the fix, and write a postmortem.
Today this is manual, slow, and inconsistent across engineers. Sentinel automates the
diagnostic and drafting work while keeping a human as the final authority on any
state-changing action.

**Why this requires LangGraph, not a linear chain:**
A linear chain (retrieve → generate → done) cannot model this workflow because the
control flow is genuinely cyclic and conditional, not sequential:

- *Diagnosis is iterative.* If retrieved context scores low on relevance/faithfulness
  (self-RAG grading), the graph must loop back to re-route and re-retrieve with a
  reformulated query — an explicit cycle, not a retry wrapper bolted onto a chain.
- *Execution can fail and must re-plan.* If a remediation action fails (e.g., a
  rollback errors out), the graph re-enters the diagnosis subgraph with the failure as
  new evidence, rather than terminating.
- *The graph must pause indefinitely for a human.* Between "propose remediation" and
  "execute remediation" the process must suspend — potentially for minutes or hours —
  and resume exactly where it left off, with full state intact. This requires durable
  execution with checkpointing, which a stateless chain cannot provide.
- *Branching is conditional on model confidence and guardrail verdicts*, not fixed
  order: low-confidence diagnoses route to escalation; guardrail failures route to a
  rejection node instead of execution.

This is precisely the class of problem LangGraph's graph-of-nodes-with-state model
exists for: persistent state, conditional edges, cycles, and interrupt/resume.

**Why this requires LangSmith:**
Every run produces a multi-node trace (router → retriever → reranker → grader →
generator → guardrail → human-approval → executor → postmortem-writer) spanning
multiple LLM calls and tool calls, often across a paused/resumed session. Debugging
*which node* caused a bad outcome, and building eval datasets from real traces, is not
feasible without structured tracing. LangSmith is also the source of the
fine-tuning data pipeline (Pillar 6) and the LLM-as-judge eval harness (Pillar 4).

**Success criteria (v1):**
1. End-to-end run from synthetic alert → human-approved remediation → postmortem draft,
   fully traced in LangSmith.
2. Self-RAG loop measurably improves context relevance (ragas `context_precision`) vs.
   a single-shot retrieval baseline, on the golden eval set.
3. Zero remediation tool calls execute without passing through the HITL interrupt node.
4. All model calls (100%) are observed flowing through the AI Gateway in LangSmith
   traces (verifiable by gateway header/metadata on every span).
5. A fine-tuned small retrieval model outperforms the off-the-shelf base embedding
   model on the golden eval set's retrieval metrics.

---

## 2. Architecture Decision Records

### ADR-001: Orchestration framework is LangGraph, not a LangChain `Chain`/`Runnable` pipeline
- **Context:** Need cyclic control flow, durable interrupt/resume, and explicit state.
- **Decision:** Use LangGraph `StateGraph` as the single orchestration backbone for the
  entire application. LangChain is used only for component primitives (retrievers,
  document loaders, prompt templates) inside graph nodes — never as the top-level
  control flow.
- **Consequences:** Slightly more boilerplate (explicit state schema, node functions)
  than a chain, in exchange for cycles, conditional routing, and interrupts.
- **Status:** Accepted.

### ADR-002: Checkpointer/persistence — Postgres, not in-memory or SQLite, from day one
- **Context:** HITL interrupts must survive process restarts (an approval may sit
  pending for hours; the API process may redeploy in the meantime). An in-memory or
  SQLite checkpointer cannot guarantee this in a multi-instance deployment.
- **Decision:** Use `langgraph.checkpoint.postgres.PostgresSaver` against the same
  Postgres instance used for pgvector, from the first commit. SQLite is explicitly
  rejected even for local dev to avoid a checkpointer migration later — local dev runs
  against a docker-composed Postgres.
- **Consequences:** Slightly heavier local dev setup (docker-compose required from
  day 1); in exchange, no "migrate the checkpointer" rewrite later and realistic
  interrupt/resume testing from the start.
- **Status:** Accepted.

### ADR-003: AI Gateway — LiteLLM Proxy sits in front of every model call
- **Context:** Pillars 3 and 5 must be infrastructure, not optional features bolted on
  per-node. If only some nodes call the gateway, fallback/caching/rate-limiting and
  guardrail coverage become inconsistent and untestable.
- **Decision:** Stand up `litellm` as a proxy server (its own process/container) on day
  one. Every LangChain/LangGraph LLM client in the codebase is configured with
  `base_url` pointed at the LiteLLM proxy — there is no code path that calls
  OpenAI/Anthropic SDKs directly. Enforced via a lint rule (see ADR-006).
- **Consequences:** One more service to run locally (docker-compose), but fallback
  chains (e.g., GPT-4o-mini → Claude Haiku), Redis semantic caching, and per-key rate
  limits are configured once, centrally, instead of per-node.
- **Status:** Accepted.

### ADR-004: Guardrails — Llama Guard 3 at every graph entry/exit node, stubbed but wired from commit 1
- **Context:** Same risk as ADR-003 — if guardrail hooks are added per-feature, some
  entry points will ship unmoderated.
- **Decision:** Define a `guardrail_check(text, direction: "input"|"output") -> GuardrailVerdict`
  utility from the first commit, backed by Llama Guard 3-8B served via the LiteLLM
  gateway (so it also benefits from ADR-003's caching/fallback). Every graph node that
  either (a) receives raw user/alert text or (b) emits text that could reach a human or
  a tool call, invokes this hook. In v1 the moderation logic itself returns a hardcoded
  `safe` verdict — the function signature, the node wiring, and the LangSmith span are
  real; only the model decision is stubbed. Open Question #1 (§7) tracks unstubbing
  it. *(Corrected by ADR-019/Feature 13 — this originally misnamed "Pillar 4," which
  is Evals, not Guardrails; the actual tracking mechanism is the Open Question.)*
- **Consequences:** No node can "forget" to add moderation later, because the call site
  already exists; turning the stub into a real check is a one-function change, not a
  graph rewire.
- **Status:** Accepted.

### ADR-005: Self-correcting structural flaw — Evals strategy was originally untestable
- **Context (self-critique):** The first draft of this PMA proposed "LLM-as-judge grades
  remediation quality" as the eval strategy for the diagnosis/remediation nodes, with no
  ground truth defined. That is not a testable eval — an LLM judge without a rubric or
  reference answer just measures the judge's own bias, and there was no golden dataset
  committed anywhere, meaning Pillar 4 would have shipped as a TODO disguised as a
  pillar.
- **Decision:** Two concrete fixes, both required before Phase 2 work begins:
  1. A versioned golden eval set (`evals/golden_incidents.jsonl`) of 20+ synthetic
     incidents is authored and committed in `evals/`, each with a reference root cause,
     a reference remediation, and a pass/fail rubric — not just a prompt.
  2. The LLM-as-judge prompt is itself a tracked artifact (`evals/judge_prompt.md`)
     with explicit binary criteria (correct root cause? safe action? within policy?)
     rather than an open-ended "rate 1-10" prompt, and it is registered as a LangSmith
     custom evaluator, not an ad hoc script.
  Retrieval-specific quality (separate from end-to-end remediation quality) is measured
  with `ragas` (`context_precision`, `context_recall`, `faithfulness`) against the same
  golden set's reference documents.
- **Consequences:** Eval work front-loads dataset authoring before any feature coding,
  which is intentional friction — it forces the rubric to exist before the agent that
  will be judged by it.
- **Status:** Accepted (supersedes the unstated implicit v0 strategy).

### ADR-006: Enforcement of ADR-003/ADR-004 via static check
- **Context:** "Wire it from day one" is only real if it's enforced, not just stated.
- **Decision:** A pre-commit/CI grep-based lint rejects any import of `openai`,
  `anthropic`, or direct `ChatOpenAI(base_url=None)`-style construction outside of
  `src/gateway/`. All model clients must be constructed through
  `src/gateway/client_factory.py`.
- **Consequences:** Slight rigidity in how nodes get their LLM client, in exchange for
  a structural guarantee instead of a convention.
- **Status:** Accepted.

### ADR-007: Repository scaffolding for infra bootstrap (Feature 01)
- **Context:** ADRs 001–006 establish *what* must be true (gateway-only calls, stubbed
  guardrails, Postgres-backed checkpointing) but not the concrete repo layout or pinned
  tool versions needed to start coding.
- **Decision:**
  - Repo layout: `src/gateway/client_factory.py`, `src/guardrails/check.py`,
    `src/graph/state.py`, `src/graph/build.py`, `infra/docker-compose.yml`.
  - `docker-compose.yml` provisions: `postgres:16` with `pgvector` enabled, `redis:7`,
    and `litellm` (proxy mode) as separate networked services.
  - `client_factory.py` exposes `get_chat_client(model: str)` and
    `get_embedding_client(model: str)`, both reading `base_url` from
    `LITELLM_PROXY_URL` — no other client-construction path exists in the codebase.
  - `guardrail_check(text: str, direction: Literal["input","output"]) -> GuardrailVerdict`
    lives in `src/guardrails/check.py`; v1 body unconditionally returns
    `GuardrailVerdict(verdict="safe", reason="stub")`.
  - The ADR-006 lint is implemented as `scripts/lint_gateway_usage.sh`, run in CI and
    as a pre-commit hook.
- **Consequences:** Every subsequent feature builds inside this layout; changing it
  later is itself a retrofit.
- **Status:** Accepted.

### ADR-008: Eval harness implementation — dataset schema, judge prompt structure, CI separation (Feature 02)
- **Context:** ADR-005 mandated a versioned golden dataset and a rubric-based judge
  registered as a LangSmith evaluator, but didn't pin the exact schema, prompt
  structure, or how the eval job relates to the PyTest suite.
- **Decision:**
  - Golden dataset schema (`evals/golden_incidents.jsonl`): one JSON object per line
    with `incident_id`, `alert_text`, `reference_root_cause`, `reference_remediation`
    (`{tool, args}`), `rubric` (list of `{criterion, description}`), `reference_docs`.
  - Judge prompt (`evals/judge_prompt.md`) renders one explicit yes/no question per
    `rubric[].criterion`, requests structured JSON `{"<criterion>": true|false, ...}` —
    never a 1–10 scale. Aggregate pass = all criteria `true`.
  - Both the LangSmith judge's LLM call and ragas's internal LLM calls go through
    `client_factory.get_chat_client(...)` — same gateway enforcement as every other
    model call (ADR-003/006).
  - The eval harness runs as its own CI job (`make eval`), separate from `pytest`,
    producing a score artifact compared against a stored baseline (Workflow
    Blueprint's Probabilistic Tier, §8.2).
  - `evals/golden_incidents.jsonl` is versioned in git; edits to an existing incident's
    reference answer or rubric require a changelog note, since they silently move the
    bar for every feature's eval gate.
- **Consequences:** Dataset and judge-prompt format are now fixed contracts — changing
  the rubric's pass/fail semantics later is itself a retrofit against this ADR.
- **Status:** Accepted.

### ADR-009: Correct graph skeleton to include guardrail rejection branches; add `rejection_reason` field (Feature 03)
- **Context:** §5.2's original skeleton wrote `guardrail_input -> router` as a single
  unconditional edge, omitting the rejection branch that ADR-004, the Pillar 3
  blueprint, and Workflow Blueprint §8.1(d) all already assumed exists. Implementing
  `guardrail_input` faithfully to those sections required correcting this drafting gap
  rather than silently picking one interpretation.
- **Decision:**
  - §5.2 is corrected: `guardrail_input` has a conditional edge —
    `guardrail_input -(verdict=unsafe)-> reject` and
    `guardrail_input -(verdict=safe)-> router`.
  - A new terminal `reject` node is added: it writes `state.rejection_reason` from the
    guardrail verdict and routes to `END`.
  - `IncidentState` (§5.1) gains one additive field: `rejection_reason: Optional[str]`.
    No existing field is renamed or retyped.
  - Node implementations live in `src/graph/nodes/` (one module per node), extending
    ADR-007's scaffolding, which named `build.py` for graph assembly but not a home for
    node logic.
  - **Flagged, not yet fixed:** `guardrail_output` (§5.2) has the same single-edge gap
    relative to Pillar 3's exit-side rejection behavior. Intentionally left uncorrected
    here to keep this retrofit's blast radius scoped to `guardrail_input` — tracked as
    Open Question #6 (§7), to be retrofitted when roadmap item 8 lands.
- **Consequences:** §5.2 now accurately reflects the rejection-branch behavior every
  other section already described; no behavior changes for any node already built
  (only `guardrail_input` exists so far).
- **Status:** Accepted.

### ADR-010: Router scope is single-corpus per query (v1); corpus ingestion layout (Feature 04)
- **Context:** §3 Pillar 1's prose ("selects one or more retrievers") was never
  reconciled with §5.1's `route` field, typed as a single optional literal, not a
  list. Building `router` required resolving this rather than shipping ambiguous
  behavior.
- **Decision:**
  - `router` classifies each query into exactly **one** of `runbooks` |
    `postmortems` | `infra_code_docs` via a single structured-output call through
    `client_factory.get_chat_client(...)`, writing it to `state.route`. Multi-corpus
    fan-out is explicitly deferred (Open Question #7).
  - §3 Pillar 1's prose is corrected to "selects exactly one retriever corpus per
    query (v1 simplification)."
  - Corpus storage: single pgvector table `documents(id, corpus, content, embedding, metadata)`.
  - Corpus source files: synthetic markdown under `corpora/runbooks/`,
    `corpora/postmortems/`, `corpora/infra_code_docs/` (consistent with ADR-005's
    synthetic-data approach).
  - Ingestion script: `scripts/ingest_corpora.py`, idempotent via content-hash upsert,
    embeds through `client_factory.get_embedding_client(...)`.
  - Router node lives at `src/graph/nodes/router.py` per ADR-009's `nodes/` convention.
- **Consequences:** `route`'s cardinality is now a deliberate, documented decision;
  widening it to a list later is itself a retrofit against this ADR.
- **Status:** Accepted.

### ADR-011: Retrieved/reranked document shape; reranker confirmed as a local, non-gateway model (Feature 05)
- **Context:** §5.1 declared `retrieved_docs`/`reranked_docs` as `list[dict]` without
  pinning the dict's fields, and it was never explicit that the reranker is
  intentionally outside the gateway contract.
- **Decision:**
  - Document dict shape (both `retrieved_docs` and `reranked_docs`):
    `{"id": str, "corpus": str, "content": str, "source": str, "score": float}` —
    `reranked_docs` entries carry the cross-encoder score, overwriting rather than
    adding a second score field.
  - Retriever: pgvector cosine-similarity query against `documents` filtered by
    `corpus = state.route`, `LIMIT 20`, query embedded via
    `client_factory.get_embedding_client(...)`.
  - Reranker: `bge-reranker-base` (sentence-transformers `CrossEncoder`), run
    in-process — confirmed outside ADR-003's gateway contract by design. Returns the
    top 5 of 20 by descending score.
  - Node files: `src/graph/nodes/retriever.py`, `src/graph/nodes/reranker.py`.
- **Consequences:** Any future node reading these fields can rely on this exact shape;
  changing it later is a retrofit against this ADR.
- **Status:** Accepted.

### ADR-012: Self-RAG grading mechanics — `current_query` field, grade threshold, retry-exhaustion behavior (Feature 06)
- **Context:** §5.1 had `retry_count` but no field to hold a reformulated query, and
  the skeleton didn't specify behavior when relevance stays low after retries are
  exhausted.
- **Decision:**
  - New additive field: `current_query: Optional[str]` — initialized to `raw_alert`,
    overwritten by `grade_documents` on retry. `router`/`retriever` read
    `current_query` (falling back to `raw_alert`), not `raw_alert` directly.
  - `grade_documents` makes one structured-output call through
    `client_factory.get_chat_client(...)` returning `{"relevance_grade": float,
    "reformulated_query": Optional[str]}`.
  - Threshold: `relevance_grade < 0.6` is "low relevance" — a placeholder pending
    eval-driven tuning (Open Question #8).
  - Retry-exhaustion: if relevance is still low after `retry_count` reaches 2, the
    graph proceeds to `diagnose` anyway (graceful degradation), preserving
    `relevance_grade` so `diagnose` can hedge — a distinct degraded path, not treated
    as equivalent to an "ok" grade.
- **Consequences:** `diagnose` (roadmap item 7) must not assume `relevance_grade >=
  0.6` just because it was reached.
- **Status:** Accepted.

### ADR-013: `proposed_action` shape with `side_effecting` flag; tool registry; diagnosis confidence hedging (Feature 07)
- **Context:** §5.2's HITL/execute branching depends on knowing whether a tool is
  side-effecting, but no registry or per-action flag existed. ADR-012 required
  `diagnose` to not assume high relevance just because it was reached, but gave no
  structured way for later nodes to read that signal.
- **Decision:**
  - Tool registry (`src/tools/registry.py`): static `dict[str, {"side_effecting": bool}]`
    seeded with `restart_service`, `rollback_deploy`, `page_secondary_oncall`
    (side_effecting=True) and `fetch_additional_logs` (side_effecting=False — exists so
    §5.2's read-only branch is reachable at all).
  - `proposed_action` shape (§5.1, amended): `{"tool": str, "args": dict,
    "side_effecting": bool}` — `propose_action` attaches `side_effecting` from the
    registry.
  - New field `diagnosis_confidence: Optional[Literal["high", "low"]]` — `diagnose`
    sets `"low"` whenever `relevance_grade < 0.6` or retries were exhausted with a
    still-low grade, `"high"` otherwise.
  - `diagnose` and `propose_action` are each one structured-output call through
    `client_factory.get_chat_client(...)`.
- **Consequences:** Roadmap items 8–10 can rely on `proposed_action["side_effecting"]`
  and `state.diagnosis_confidence` as fixed contracts.
- **Status:** Accepted.

### ADR-014: Wire `guardrail_output`'s rejection branches at both call sites (Feature 08, resolves Open Question #6)
- **Context:** `guardrail_output` is called twice — after `propose_action`
  (pre-execution) and after `write_postmortem` (post-execution). Neither call site had
  an unsafe-verdict branch; ADR-009 flagged this gap and deferred it here.
- **Decision:**
  - Pre-execution call site: `unsafe -> reject`; `safe` + `side_effecting` ->
    `await_human_approval`; `safe` + read-only -> `execute`.
  - Post-execution call site: `unsafe -> reject` (the postmortem draft is not
    surfaced and `rejection_reason` is recorded — the already-executed action is
    **not** undone; `execution_result` stays in state for audit); `safe -> END`
    (unchanged).
  - Same `guardrail_output` node function at both positions; each call site's own
    conditional-edge function distinguishes them by checking whether
    `execution_result` is set.
- **Consequences:** §5.2 now has an explicit unsafe path from every guardrail node.
- **Status:** Accepted.

### ADR-015: HITL resume contract formalization; `PostgresSaver` wiring; `modified_action` precedence (Feature 09)
- **Context:** Pillar 2's prose specified the resume payload shape informally; this
  feature needed it typed, and needed a rule for how `execute` (roadmap item 10)
  reconciles a human's edit against the original proposal.
- **Decision:**
  - `HumanDecision` shape (formalizing `human_decision: Optional[dict]`):
    `{"approved": bool, "modified_action": Optional[dict], "note": str}`.
  - `modified_action` precedence: on `approved=True`, `execute` must use
    `human_decision.modified_action` if not `None`, else `proposed_action`.
  - `src/graph/build.py` compiles the graph with `PostgresSaver` against the same
    Postgres instance used for pgvector (ADR-002); `await_human_approval` uses
    LangGraph's `interrupt()`.
  - Integration tests for this boundary run against a real test-schema Postgres, per
    Workflow Blueprint §8.1's worked example (c).
  - Out of scope, deferred: the HTTP API surface (start-run / submit-approval
    endpoints) — tracked as a new Open Question.
- **Consequences:** `execute` (item 10) has an unambiguous action-precedence rule;
  the HTTP layer, whenever built, has a typed payload to deserialize into.
- **Status:** Accepted.

### ADR-016: Tool execution sandboxing — mock staging API, `execution_result` shape (Feature 10, resolves Open Question #3)
- **Context:** `execute`'s backing mechanism for the registered tools was
  unspecified, risking the Gherkin/PyTest silently encoding an unauthorized assumption
  about real vs. mock infra.
- **Decision:**
  - v1 executes against a mock staging API (`mock-staging-api`, added to
    `infra/docker-compose.yml`), never real production infrastructure.
  - Tool executors (`src/tools/executors.py`): one function per registry tool name,
    each calling `mock-staging-api` via `httpx`, dispatched by
    `proposed_action["tool"]` or `human_decision.modified_action["tool"]` per ADR-015.
  - Failure injection is configurable in test fixtures so the failure-routing path is
    deterministic, not dependent on a real outage.
  - `execution_result` shape: `{"tool": str, "args": dict, "success": bool, "output": str, "error": Optional[str]}`.
  - Gateway scope confirmed: these HTTP calls are outside ADR-003, same precedent as
    the local reranker (ADR-011).
- **Consequences:** Resolves Open Question #3. Swapping the mock for a real staging
  API later is itself a retrofit against this ADR, not a transparent config change.
- **Status:** Accepted.

### ADR-017: `write_postmortem` content sources and draft structure (Feature 11)
- **Context:** `postmortem_draft` existed as a bare string field with no specification
  of what it should contain or how it should reflect upstream signals like
  `diagnosis_confidence`.
- **Decision:**
  - `write_postmortem` makes one LLM call through `client_factory.get_chat_client(...)`,
    drafting a postmortem with four fixed sections: **Summary**, **Root Cause**,
    **Action Taken & Outcome**, **Notes**.
  - Inputs: `diagnosis`, `proposed_action` (or `human_decision.modified_action` if
    present), `execution_result`, and `human_decision.note` if the run was approved
    with caveats.
  - **Confidence-aware narrative:** if `diagnosis_confidence == "low"`, the "Notes"
    section explicitly states the diagnosis was made under degraded retrieval
    confidence — this signal (already structured per ADR-013) is not silently
    dropped at the final reporting step.
  - The draft is then passed through `guardrail_output`'s post-execution call site
    (ADR-014) before `END`.
- **Consequences:** Establishes what "the postmortem" actually contains; changing the
  section structure later is a retrofit against this ADR.
- **Status:** Accepted.

### ADR-018: LiteLLM proxy production configuration — fallback, caching with an eval carve-out, per-key rate limits, trace_id propagation (Feature 12)
- **Context:** ADR-003 named fallback/caching/rate-limiting as the gateway's payoff
  but never configured any of it. Configuring caching naively would also silently
  conflict with ADR-005's eval-determinism requirement.
- **Decision:**
  - Model aliases (`infra/litellm_config.yaml`, e.g. `sentinel-chat`,
    `sentinel-embedding`) each declare a primary + fallback provider model via
    LiteLLM's native `fallbacks` list; `client_factory` passes alias names, not raw
    provider model strings.
  - Redis-backed semantic caching enabled proxy-wide for application traffic.
  - **Eval-determinism carve-out:** every eval harness call (ragas,
    `sentinel_remediation_judge`) sends `cache={"no-cache": True}`, guaranteeing eval
    runs always hit a live model — only graph-node traffic is cache-eligible.
  - Three virtual keys (`sentinel-app`, `sentinel-eval`, `sentinel-dev`), each with
    independent rate-limit/budget caps (numeric values are placeholders — new Open
    Question).
  - `client_factory` attaches `metadata={"trace_id": ...}` from the active LangSmith
    run on every request, joining proxy cost/usage logs to LangSmith traces
    (Project Charter success criterion 4).
- **Consequences:** Fallback/caching/rate-limit specifics are now a fixed contract;
  removing the eval carve-out later is a retrofit against this ADR, not a
  transparent tuning change.
- **Status:** Accepted.

### ADR-019: Real Llama Guard 3-8B inference; `GuardrailVerdict` shape; guardrail eval dataset; corrects ADR-004's pillar reference and §8.3's `borderline` mention (Feature 13, retrofit, resolves Open Question #1)
- **Context:** `guardrail_check()` returned a hardcoded `safe` verdict since Feature
  01. Replacing it with real inference required pinning the verdict's shape, deciding
  how moderation *accuracy* gets measured, and surfaced two stale prose
  inconsistencies: ADR-004 said "Pillar 4" tracks unstubbing (it doesn't — Open
  Question #1 does; Pillar 4 is Evals), and §8.3's `@guardrail` example mentioned a
  `borderline` verdict that no ADR ever implemented.
- **Decision:**
  - `guardrail_check()` now calls
    `client_factory.get_chat_client(model="sentinel-guardrail")` — a new LiteLLM
    alias (ADR-018 pattern) backed by Llama Guard 3-8B with a fallback safety model.
  - `GuardrailVerdict` shape (formalizing `guardrail_input_verdict`/
    `guardrail_output_verdict: Optional[dict]`):
    `{"verdict": Literal["safe", "unsafe"], "reason": str, "category": Optional[str]}`
    — strictly binary, no `borderline` state.
  - Guardrail calls are normal `sentinel-app` traffic (cache-eligible per ADR-018),
    deliberately excluded from the eval-harness no-cache carve-out.
  - New eval artifact `evals/guardrail_redteam.jsonl` (labeled safe/unsafe examples)
    + a precision/recall scorer in `make eval`, measuring real moderation accuracy —
    a separate file, not a change to `golden_incidents.jsonl`'s fixed schema
    (ADR-008).
  - ADR-004's "Pillar 4" reference is corrected to point to Open Question #1; §8.3's
    `@guardrail` example is corrected to "safe/unsafe" only.
- **Consequences:** Resolves Open Question #1. `GuardrailVerdict` is now a fixed
  contract; adding fields later is additive, removing the binary constraint is a
  retrofit. Guardrail moderation accuracy is measurable for the first time.
- **Status:** Accepted.

### ADR-020: Fine-tuning data source correction; promotion criteria; local model-swap scope (Feature 14, retrofit, resolves Open Question #5)
- **Context:** Pillar 6's original prose named `grade_documents`' per-(query, doc)
  relevance grade as the contrastive-pair data source, but ADR-012 only ever defined
  an aggregate grade for the whole retrieved batch — nothing per-document existed to
  export as described. Additionally, "outperforms base on golden set" (success
  criterion 5 / Open Question #5) had no numeric promotion threshold.
- **Decision:**
  - **Corrected data source:** `scripts/export_finetune_pairs.py` exports from
    LangSmith **retriever + reranker spans**, not `grade_documents` spans — positive
    examples are top-k `reranked_docs` (by `score`, ADR-011), negatives are
    `retrieved_docs` that didn't survive re-ranking. Output: `evals/finetune_pairs.jsonl`.
  - `scripts/finetune_embedding_model.py` runs a `sentence-transformers` contrastive
    fine-tune of `BAAI/bge-small-en-v1.5`, writing a versioned artifact to
    `models/finetuned-embeddings/v{N}/`.
  - **Promotion criteria:** `scripts/ab_eval_embedding_model.py` runs ragas
    `context_precision`/`context_recall` against the golden set for both base and
    candidate models. The candidate is promoted only if it beats the last recorded
    baseline by a configured margin (placeholder value — new Open Question), recorded
    as a new Feature Log baseline per §8.5 item 4.
  - **Config flag, local execution:** `EMBEDDING_MODEL_VARIANT=base|finetuned`
    deployment config, read by `retriever`. `finetuned` loads the local model
    in-process — outside ADR-003's gateway scope, the **third** confirmation of this
    precedent (after the reranker, ADR-011, and tool execution, ADR-016). `base` is
    unchanged (`client_factory.get_embedding_client(...)`).
  - **Deferred:** fine-tuning `router`'s classification, and using
    `human_decision.note` as a structured "retrieval was wrong" signal, are both out
    of scope here.
- **Consequences:** Resolves Open Question #5 with a concrete mechanism. The
  promotion margin's numeric value is a new placeholder (Open Question). Pillar 6's
  prose now accurately describes the real data source.
- **Status:** Accepted.

---

## 3. Production RAG Blueprint

### Pillar 1 — Advanced RAG Mechanics
- **Query routing:** A `router` node (small/cheap LLM call through the gateway)
  classifies the incoming query against three corpora — `runbooks`, `postmortems`,
  `infra_code_docs` — and selects exactly one retriever corpus per query (v1
  simplification — see ADR-010; multi-corpus fan-out deferred, Open Question #7).
  Implemented as a LangGraph conditional edge, not an LCEL `RouterChain`, so routing
  decisions are first-class graph state and visible in LangSmith as a distinct span.
- **Re-ranking:** Initial vector retrieval (pgvector, top-k=20) is followed by a
  cross-encoder re-rank step (`BAAI/bge-reranker-base`, run locally — no extra API
  dependency) down to top-k=5 before generation.
- **Self-RAG / reflection:** A `grade_documents` node scores the re-ranked context for
  relevance (structured-output LLM call). If grade < threshold, a conditional edge
  routes back to the `router` node with a reformulated query (max 2 retries tracked in
  state), instead of proceeding to generation. This is the graph's primary cycle.
- **Implementation status (Feature 04):** Corpus ingestion (`scripts/ingest_corpora.py`
  → single `documents` pgvector table, tagged by `corpus`) and the `router` node
  (single structured classification call writing `state.route`) are implemented per
  ADR-010. Re-ranking and `grade_documents` remain roadmap items 5–6; ragas
  `context_precision`/`context_recall` still have nothing to score until item 5's
  `retriever` node exists. See
  `/memory/features/feature-04-ingestion-router-node.md`.
- **Implementation status (Feature 05):** `retriever` (pgvector top-k=20 against
  `state.route`'s corpus) and `reranker` (`bge-reranker-base` cross-encoder down to
  top-k=5, run locally, outside the gateway by design) implemented per ADR-011.
  `grade_documents`/self-RAG retry remains roadmap item 6. See
  `/memory/features/feature-05-retriever-reranker-nodes.md`.
- **Implementation status (Feature 06):** `grade_documents` implemented per ADR-012:
  scores relevance, loops back to `router` with a reformulated `current_query` when
  low (capped at 2 retries), and degrades gracefully to `diagnose` if still low after
  retries are exhausted. Pillar 1 (routing → retrieval → re-ranking → self-RAG) is now
  design-complete end to end; `diagnose`/`propose_action` are roadmap item 7. See
  `/memory/features/feature-06-grade-documents-self-rag.md`.
- **Implementation status (Feature 07):** `diagnose` (the "generation" step this
  pillar's prose pointed to but never detailed) implemented per ADR-013, with a
  structured `diagnosis_confidence` signal honoring ADR-012's hedging requirement. See
  `/memory/features/feature-07-diagnose-propose-action-nodes.md`.
- **Implementation status (Feature 14):** `retriever`'s embedding call gains a second,
  swappable code path (`EMBEDDING_MODEL_VARIANT=base|finetuned`) per ADR-020; the
  document shape ADR-011 pinned is unaffected either way. See
  `/memory/features/feature-14-finetuning-pipeline.md`.

### Pillar 2 — Human-in-the-Loop State Management
- **Mechanism:** LangGraph `interrupt()` inside an `await_human_approval` node, placed
  immediately before any node tagged `side_effecting=True` (e.g., `restart_service`,
  `rollback_deploy`, `page_secondary_oncall`).
- **Persistence:** `PostgresSaver` (ADR-002) — the graph can be interrupted, the process
  can restart, and `graph.invoke(None, config={"configurable": {"thread_id": ...}})`
  resumes exactly at the approval node once a human responds via the API.
- **Resume contract:** the approval response is a structured `{approved: bool,
  modified_action: Optional[dict], note: str}` written back into graph state, never a
  free-text reinterpretation.
- **Implementation status (Feature 07):** groundwork only — `propose_action` now
  attaches `side_effecting: bool` to `proposed_action` via the tool registry
  (ADR-013), which is what `await_human_approval` (roadmap item 9) will branch on. The
  interrupt node itself does not exist yet. See
  `/memory/features/feature-07-diagnose-propose-action-nodes.md`.
- **Implementation status (Feature 09):** `await_human_approval` (`interrupt()`) and
  `PostgresSaver` wiring in `src/graph/build.py` implemented per ADR-015. Resume
  routing (`approved -> execute`, `rejected -> diagnose`) is wired; `execute` itself
  is roadmap item 10. The HTTP API layer for starting runs/submitting decisions is
  explicitly deferred (Open Question #10). See
  `/memory/features/feature-09-await-human-approval-node.md`.
- **Implementation status (Feature 10):** `execute` implemented per ADR-016 against a
  mock staging API (resolves Open Question #3), dispatching via the tool registry and
  honoring ADR-015's `modified_action` precedence. Project Charter success criterion 3
  is now end-to-end verifiable. See `/memory/features/feature-10-execute-node.md`.

### Pillar 3 — Guardrails
- **Library:** Llama Guard 3-8B, served as a model behind the LiteLLM gateway (so it is
  itself cached/fallback-protected).
- **Placement:** Every graph entry node (raw alert/user text in) and every exit node
  (remediation explanation, postmortem draft, any text reaching the human or a tool)
  calls the shared `guardrail_check()` hook (ADR-004). v1 ships the hook wired with a
  stub verdict; unstubbing is a tracked Open Question, not a deferred pillar.
- **Implementation status (Feature 01):** `guardrail_check()` exists in
  `src/guardrails/check.py` and unconditionally returns a `safe` verdict. No graph node
  calls it yet — that wiring happens per-node as each node is built (roadmap items 3,
  8). See `/memory/features/feature-01-infra-bootstrap.md`.
- **Implementation status (Feature 03):** `guardrail_input` is the first real call
  site: it invokes `guardrail_check()` on `raw_alert` and routes to a new `reject` node
  on an unsafe verdict, `router` otherwise (ADR-009 corrects §5.2 to make this explicit
  and adds `state.rejection_reason`). Still against the stub verdict — only the
  trigger-routing wiring is real. See
  `/memory/features/feature-03-guardrail-input-node.md`.
- **Implementation status (Feature 08):** `guardrail_output` now has unsafe-verdict
  routing at both call sites (pre-execution -> `reject`; post-execution -> `reject`
  without undoing the already-executed action) per ADR-014, closing the gap Open
  Question #6 tracked. Still against the stub verdict. See
  `/memory/features/feature-08-guardrail-output-node.md`.
- **Implementation status (Feature 11):** the post-execution call site is now
  exercisable end-to-end for the first time — `write_postmortem` (ADR-017) produces a
  real `postmortem_draft` for `guardrail_output` to moderate, rather than an empty
  field. Still against the stub verdict. See
  `/memory/features/feature-11-write-postmortem-node.md`.
- **Implementation status (Feature 13):** `guardrail_check()` now performs real
  Llama Guard 3-8B inference through the gateway (resolves Open Question #1) per
  ADR-019, with `GuardrailVerdict`'s shape formalized (`verdict`, `reason`,
  `category`). Both call sites' routing logic is unchanged — only the verdict source
  is real now. See `/memory/features/feature-13-guardrail-unstubbing.md`.

### Pillar 4 — LLM Evals
- **Dataset:** `evals/golden_incidents.jsonl`, versioned, with reference root cause +
  reference remediation + binary rubric per incident (ADR-005).
- **Retrieval metrics:** `ragas` — `context_precision`, `context_recall`,
  `faithfulness`, run in CI against the golden set whenever retrieval-affecting code
  changes.
- **End-to-end metrics:** LangSmith custom evaluator running the rubric-based
  LLM-as-judge prompt (`evals/judge_prompt.md`) over full graph traces, scored as
  pass/fail per rubric criterion, aggregated per run.
- **Implementation status (Feature 02):** Dataset schema, judge prompt structure, and
  LangSmith evaluator registration (`sentinel_remediation_judge`) implemented per
  ADR-008; runs as a separate `make eval` CI job. No baseline score recorded yet — the
  harness has no real graph output to score until roadmap items 4–11 exist. See
  `/memory/features/feature-02-eval-harness.md`.
- **Implementation status (Feature 05):** `retriever`/`reranker` (ADR-011) give the
  harness real retrieval output for the first time. The first ragas
  `context_precision`/`context_recall` baseline is recordable once this feature's code
  lands and `make eval` runs — not yet measured at design stage. End-to-end judge
  scoring still waits on `diagnose`/`propose_action` (roadmap item 7). See
  `/memory/features/feature-05-retriever-reranker-nodes.md`.
- **Implementation status (Feature 07):** `sentinel_remediation_judge` (ADR-008) can
  now run meaningfully for the first time: `diagnosis` and `proposed_action` (ADR-013)
  exist to compare against `golden_incidents.jsonl`'s reference fields. First baseline
  recorded once this feature's code lands, not yet at design stage. See
  `/memory/features/feature-07-diagnose-propose-action-nodes.md`.
- **Implementation status (Feature 12):** the eval-determinism carve-out in ADR-018
  (`cache: no-cache` on every eval harness call) is now the explicit mechanism that
  keeps `make eval` baselines valid once gateway-wide semantic caching exists — without
  it, a cached stale response could silently mask a real model-behavior regression. See
  `/memory/features/feature-12-litellm-proxy-hardening.md`.
- **Implementation status (Feature 13):** new `evals/guardrail_redteam.jsonl` +
  precision/recall scorer (run in `make eval`) gives Pillar 3's moderation-accuracy
  surface (already named in §8.2) a real dataset for the first time, separate from
  `golden_incidents.jsonl`'s fixed schema (ADR-008). See
  `/memory/features/feature-13-guardrail-unstubbing.md`.

### Pillar 5 — AI Gateway
- **Library:** LiteLLM Proxy (ADR-003), own service, all model traffic routed through
  it.
- **Configured behaviors:** fallback chain (primary → secondary model on error/timeout),
  Redis-backed semantic response caching, per-API-key rate limiting, and unified
  cost/usage logging exported alongside LangSmith traces via shared `trace_id` metadata.
- **Implementation status (Feature 01):** `src/gateway/client_factory.py` exists and is
  the sole construction path for chat/embedding clients, pointed at `LITELLM_PROXY_URL`.
  Fallback chains, semantic caching, and rate limits are NOT yet configured on the
  proxy itself — that substantive configuration is roadmap item 12. See
  `/memory/features/feature-01-infra-bootstrap.md`.
- **Implementation status (Feature 12):** `infra/litellm_config.yaml` implemented per
  ADR-018 — model-alias fallback chains, Redis-backed semantic caching (with an
  eval-determinism carve-out), three rate-limited/budgeted virtual keys, and
  trace_id-tagged cost/usage logging. Project Charter success criterion 4 is now
  end-to-end verifiable. See
  `/memory/features/feature-12-litellm-proxy-hardening.md`.

### Pillar 6 — Fine-Tuning Integration
- **What gets fine-tuned:** A small embedding/retrieval model
  (`BAAI/bge-small-en-v1.5`), not the main LLM. Target (v1 scope, per ADR-020):
  improve retrieval ranking for this project's specific corpora; fine-tuning
  `router`'s classification is deferred.
- **Data source:** LangSmith traces of the `retriever` and `reranker` nodes — each
  re-ranked document's cross-encoder `score` (ADR-011) is a real per-document
  relevance signal; positive examples are top-k `reranked_docs`, negatives are
  `retrieved_docs` that didn't survive re-ranking, exported via the LangSmith SDK into
  contrastive training pairs for the same query. *(Corrected by ADR-020/Feature 14 —
  this originally named `grade_documents` traces and a per-document
  `relevance_grade`, but ADR-012 only ever defined an aggregate grade for the whole
  batch; nothing per-document existed there to export.)* Using
  `human_decision.note`'s free text as a structured "retrieval was wrong" signal
  remains out of scope (the field is unstructured per ADR-015).
- **Pipeline:** `scripts/export_finetune_pairs.py` (LangSmith → `evals/finetune_pairs.jsonl`)
  → `scripts/finetune_embedding_model.py` (`sentence-transformers` contrastive
  fine-tune) → versioned model artifact (`models/finetuned-embeddings/v{N}/`) →
  swapped into the retriever via `EMBEDDING_MODEL_VARIANT=base|finetuned`, A/B-evaluated
  (`ragas context_precision`/`context_recall`) against the golden set; promoted only if
  it beats the recorded baseline by a configured margin (Open Question #14).
- **Implementation status (Feature 14):** fully implemented per ADR-020 — export
  script, fine-tune script, A/B promotion gate, and the local in-process model-swap
  (confirmed a third time outside the gateway's scope, after ADR-011/ADR-016). Project
  Charter success criterion 5 is now end-to-end verifiable, pending an actual training
  run and recorded baseline. See `/memory/features/feature-14-finetuning-pipeline.md`.

---

## 4. Tech Stack

| Layer | Choice | One-line reason |
|---|---|---|
| Orchestration | `langgraph` | Cyclic state machine + native interrupt/resume (ADR-001) |
| LLM framework | `langchain` (components only) | Reusable retriever/loader/prompt primitives, not top-level control flow |
| Tracing/eval | `langsmith` | Tracing, dataset management, LLM-as-judge custom evaluators |
| Gateway | `litellm` (proxy mode) | Single chokepoint for fallback/caching/rate-limit (ADR-003) |
| Guardrails | Llama Guard 3-8B (via gateway) | Open-weight, purpose-built input/output moderation classifier |
| Vector store | Postgres + `pgvector` | One database for both vectors and graph checkpoints — fewer moving parts |
| Checkpointer | `langgraph-checkpoint-postgres` | Durable interrupt persistence across restarts (ADR-002) |
| Re-ranker | `BAAI/bge-reranker-base` (local) | No added API dependency for a step that runs on every query |
| Evals | `ragas` + LangSmith custom evaluators | Retrieval metrics (ragas) + rubric-based end-to-end judge (LangSmith) |
| Fine-tuning | `sentence-transformers` | Standard, lightweight contrastive fine-tuning for small embedding models |
| Cache | Redis | Backing store for LiteLLM semantic cache |
| API layer | FastAPI | Async-native, pairs cleanly with LangGraph's async invoke/stream |
| Spec/BDD | `behave` (Gherkin) | Human-readable feature specs gating implementation (Phase 2) |
| Testing | `pytest` + `pytest-asyncio` | Unit/integration tests for nodes, graph, and gateway config |
| Local infra | `docker-compose` (Postgres, Redis, LiteLLM proxy) | Reproducible local env matching ADR-002/003 from day one |

---

## 5. Active Contracts

### 5.1 Graph state schema (initial, will be retrofitted via Phase 3 process)

```python
from typing import TypedDict, Literal, Optional
from langgraph.graph import add_messages
from typing_extensions import Annotated

class IncidentState(TypedDict):
    raw_alert: str
    guardrail_input_verdict: Optional[dict]      # GuardrailVerdict: {"verdict": Literal["safe","unsafe"], "reason": str, "category": Optional[str]} (formalized ADR-019)
    route: Optional[Literal["runbooks", "postmortems", "infra_code_docs"]]
    retrieved_docs: list[dict]
    reranked_docs: list[dict]
    relevance_grade: Optional[float]              # self-RAG signal
    retry_count: int
    diagnosis: Optional[str]
    diagnosis_confidence: Optional[Literal["high", "low"]]  # set by diagnose (ADR-013)
    proposed_action: Optional[dict]                # {"tool": str, "args": dict, "side_effecting": bool} (ADR-013)
    human_decision: Optional[dict]                 # HumanDecision: {"approved": bool, "modified_action": Optional[dict], "note": str} (formalized ADR-015)
    execution_result: Optional[dict]               # {"tool": str, "args": dict, "success": bool, "output": str, "error": Optional[str]} (ADR-016)
    guardrail_output_verdict: Optional[dict]     # GuardrailVerdict, same shape as guardrail_input_verdict (ADR-019)
    postmortem_draft: Optional[str]
    rejection_reason: Optional[str]               # set by `reject` node (ADR-009)
    current_query: Optional[str]                  # query text for router/retriever; init = raw_alert, overwritten on retry (ADR-012)
    thread_id: str
```

### 5.2 Graph skeleton (node/edge names only — implementation is Phase 2+)

```
entry -> guardrail_input
guardrail_input -(verdict=unsafe)-> reject
guardrail_input -(verdict=safe)-> router
reject -> END
router -> retriever
retriever -> reranker
reranker -> grade_documents
grade_documents -(low relevance, retry_count<2)-> router
grade_documents -(ok)-> diagnose
diagnose -> propose_action
propose_action -> guardrail_output
guardrail_output -(unsafe, pre-execution)-> reject
guardrail_output -(safe, side_effecting action)-> await_human_approval   [interrupt]
guardrail_output -(safe, read-only action)-> execute
await_human_approval -(approved)-> execute
await_human_approval -(rejected)-> diagnose
execute -(failure)-> diagnose
execute -(success)-> write_postmortem
write_postmortem -> guardrail_output
guardrail_output -(unsafe, post-execution)-> reject
guardrail_output -(safe, post-execution)-> END
```

### 5.3 Gateway contract
- Every LLM/embedding client constructed only via `src/gateway/client_factory.py`,
  pointed at the LiteLLM proxy `base_url`. Direct provider SDK imports outside
  `src/gateway/` fail CI (ADR-006).

---

## 6. Feature Log

| Feature ID | Description | Phase Introduced | Status | PMA Sections Touched |
|---|---|---|---|---|
| `feature-01-infra-bootstrap` | docker-compose infra, `client_factory.py`, `guardrail_check()` stub, `IncidentState` schema, empty entry→END graph | Phase 4 | In Progress | ADR-007 (new), §3 Pillar 3, §3 Pillar 5, §9 item 1 |
| `feature-02-eval-harness` | `evals/golden_incidents.jsonl`, `evals/judge_prompt.md`, ragas + LangSmith evaluator wiring, `make eval` CI job | Phase 4 | In Progress | ADR-008 (new), §3 Pillar 4, §9 item 2 |
| `feature-03-guardrail-input-node` | `guardrail_input` node + new `reject` node; corrects §5.2 to include the rejection branch | Phase 4 | In Progress | ADR-009 (new, retrofit), §5.1, §5.2, §3 Pillar 3, §9 item 3 |
| `feature-04-ingestion-router-node` | Corpus ingestion into pgvector + `router` node; corrects Pillar 1 prose to single-corpus routing | Phase 4 | In Progress | ADR-010 (new, retrofit), §3 Pillar 1, §9 item 4 |
| `feature-05-retriever-reranker-nodes` | `retriever` (pgvector top-k=20) + `reranker` (bge-reranker-base top-k=5) nodes; pins document dict shape | Phase 4 | In Progress | ADR-011 (new), §3 Pillar 1, §3 Pillar 4, §9 item 5 |
| `feature-06-grade-documents-self-rag` | `grade_documents` node + self-RAG retry loop; adds `current_query` field and retry-exhaustion behavior | Phase 4 | In Progress | ADR-012 (new), §5.1, §3 Pillar 1, §9 item 6 |
| `feature-07-diagnose-propose-action-nodes` | `diagnose` + `propose_action` nodes; adds tool registry, `side_effecting` flag, `diagnosis_confidence` field | Phase 4 | In Progress | ADR-013 (new), §5.1, §3 Pillar 1, §3 Pillar 2, §3 Pillar 4, §9 item 7 |
| `feature-08-guardrail-output-node` | `guardrail_output` node; wires unsafe-verdict rejection branches at both call sites (deferred retrofit from ADR-009) | Phase 4 | In Progress | ADR-014 (new, retrofit), §5.2, §3 Pillar 3, §9 item 8 |
| `feature-09-await-human-approval-node` | `await_human_approval` interrupt node + `PostgresSaver` wiring; formalizes `HumanDecision` shape and `modified_action` precedence | Phase 4 | In Progress | ADR-015 (new), §5.1, §3 Pillar 2, §9 item 9 |
| `feature-10-execute-node` | `execute` node against a mock staging API; resolves Open Question #3, pins `execution_result` shape | Phase 4 | In Progress | ADR-016 (new), §5.1, §3 Pillar 2, §9 item 10 |
| `feature-11-write-postmortem-node` | `write_postmortem` node; drafts a 4-section postmortem from diagnosis/action/execution_result, confidence-aware notes, into `guardrail_output`'s post-execution branch | Phase 4 | In Progress | ADR-017 (new), §3 Pillar 3, §7 (new Open Question), §9 item 11 |
| `feature-12-litellm-proxy-hardening` | LiteLLM proxy production config: fallback chains, semantic caching with eval carve-out, per-key rate limits, trace_id-tagged cost logging | Phase 4 | In Progress | ADR-018 (new), §5.3, §3 Pillar 5, §3 Pillar 4, §7 (new Open Question), §9 item 12 |
| `feature-13-guardrail-unstubbing` | Real Llama Guard 3-8B inference replaces the `guardrail_check()` stub; formalizes `GuardrailVerdict` shape; adds `evals/guardrail_redteam.jsonl`; corrects ADR-004's pillar reference and §8.3's `borderline` mention | Phase 4 | In Progress | ADR-019 (new, retrofit), §5.1, §8.3, §3 Pillar 3, §3 Pillar 4, §7 (resolves Open Question #1, new Open Question), §9 item 13 |
| `feature-14-finetuning-pipeline` | Fine-tuning export/train/A-B-promote pipeline for the embedding model; corrects Pillar 6's data-source prose to retriever/reranker spans; resolves Open Question #5 | Phase 4 | In Progress | ADR-020 (new, retrofit), §3 Pillar 6, §3 Pillar 1, §7 (resolves Open Question #5, new Open Question), §9 item 14 |

---

## 7. Open Questions / Risks

1. **Guardrail stub unstubbing date:** Llama Guard verdicts are hardcoded `safe` in v1
   (ADR-004). Must be replaced with real inference before any non-synthetic data touches
   the system. Tracked, not yet scheduled to a phase. **Resolved by ADR-019**
   (Feature 13): real Llama Guard 3-8B inference now backs both call sites.
2. **Synthetic vs. real incident data:** the golden eval set (ADR-005) is currently
   100% synthetic. Risk: synthetic incidents may not reflect real failure-mode
   distribution. Mitigation TBD — possibly seed from public postmortem corpora
   (e.g., publicly published company postmortems) once licensing is checked.
3. **Tool execution sandboxing:** `execute` node design (what `restart_service` /
   `rollback_deploy` actually call) is unspecified — likely mocked tool calls against a
   staging API in v1, not real production infra. Must be explicit before Phase 2 BDD
   feature files are written, or the Gherkin specs will encode a false assumption.
   **Resolved by ADR-016** (Feature 10): v1 executes against a mock staging API
   service, never real infra; swapping it later is itself a tracked retrofit.
4. **Cost of self-RAG retry loop:** unbounded retries could spike gateway cost; current
   cap is `retry_count < 2` (hardcoded) — revisit once caching metrics exist.
5. **Fine-tuned model promotion criteria:** "outperforms base on golden set" (success
   criterion 5) needs a numeric threshold, not just directional improvement — to be
   defined when Pillar 6 is implemented, not deferred indefinitely. **Resolved by
   ADR-020** (Feature 14): promotion requires beating the recorded baseline's
   `context_precision` by a configured margin, gated through `ab_eval_embedding_model.py`.
6. **`guardrail_output` rejection branch not yet wired:** Feature 03 (ADR-009) added
   the rejection branch only on the `guardrail_input` side. §5.2's `guardrail_output`
   edges still need the same retrofit (a `reject` branch on an unsafe output verdict)
   when roadmap item 8 is built — do not let item 8 ship without revisiting this.
   **Resolved by ADR-014** (Feature 08): both call sites now have unsafe-verdict
   routing to `reject`.
7. **Multi-corpus fan-out deferred:** Feature 04 (ADR-010) restricted `router` to
   exactly one corpus per query, deferring the "one or more retrievers" idea from
   Pillar 1's original prose. If a real incident genuinely needs evidence from more
   than one corpus, this will need a deliberate retrofit of `route`'s cardinality —
   not a silent workaround in the `retriever` node.
8. **Self-RAG relevance threshold is a placeholder:** ADR-012 fixed `relevance_grade <
   0.6` as the low-relevance cutoff with no empirical basis yet. Must be revisited once
   the eval harness (Pillar 4) has a real baseline to tune against — likely after
   roadmap item 7.
9. **`diagnose` re-entry behavior is unscoped:** Feature 07 only specifies `diagnose`
   for the first-pass case. `await_human_approval -(rejected)-> diagnose` (item 9) and
   `execute -(failure)-> diagnose` (item 10) both re-enter `diagnose` with different
   context (a human's rejection note, or an execution failure) — how `diagnose` should
   use that context is not yet designed. **Partially de-risked by Feature 09:** the
   `rejected -> diagnose` edge is now wired and testable, but `diagnose`'s actual
   prompt/behavior still doesn't differentiate first-pass from re-entry. Still open for
   `execute -(failure)-> diagnose` (item 10) and for `diagnose`'s prompt logic.
10. **HTTP API layer is undesigned:** Feature 09 deliberately deferred the endpoints a
    human (or UI) would actually use to start a run and submit an approval decision.
    No Active Contract exists for this yet. Needs its own design pass — likely as part
    of or after roadmap item 10, since `execute` and the API surface are closely
    related (the API is also how execution results would realistically be observed).
11. **No retry cap on `execute -(failure)-> diagnose`:** unlike the self-RAG loop's
    `retry_count < 2` (ADR-012), there is no bound on how many times execution can
    fail and re-enter `diagnose`. A persistently-failing remediation could cycle
    indefinitely. Flagged during Feature 11 (it surfaced because `write_postmortem`
    is the node such a run would never reach) but out of scope for that feature —
    this is a `diagnose`/`execute` concern to resolve in a future retrofit.
12. **LiteLLM virtual-key rate-limit/budget caps are placeholders:** ADR-018 (Feature
    12) set up three virtual keys (`sentinel-app`, `sentinel-eval`, `sentinel-dev`)
    with rate-limit/budget config, but the specific numeric caps have no empirical
    basis yet — same pattern as Open Question #8's relevance threshold. Revisit once
    real usage/cost data exists.
13. **Guardrail moderation precision/recall thresholds are placeholders:** ADR-019
    (Feature 13) added `evals/guardrail_redteam.jsonl` and a precision/recall scorer,
    but no pass/fail threshold has been empirically tuned yet — same pattern as Open
    Question #8 and #12. Revisit once the scorer has run against real Llama Guard
    output.
14. **Fine-tuned model promotion margin is a placeholder:** ADR-020 (Feature 14)
    established the promotion *mechanism* (beat the recorded baseline's
    `context_precision` by a configured margin) but the margin's numeric value has no
    empirical basis yet — same pattern as Open Questions #8, #12, and #13. Revisit
    once an actual fine-tuning run and A/B eval have produced real numbers.

---

## 8. Development Workflow Blueprint

### 8.1 The loop, stated precisely

```
API/Schema Spec  -->  Gherkin (.feature)  -->  PyTest (unit + integration)  -->  Implementation  -->  Refactor
      ^                                                                                                 |
      └──────────────────────────── spec amended if refactor reveals a contract gap ────────────────────┘
```

Spec comes first and is not prose — it is a change to Section 5 (Active Contracts) or
Section 3 (Production RAG Blueprint) of this PMA, committed before any `.feature` file
is written. Gherkin scenarios are written against that spec, not against intuition.
PyTest step definitions implement the scenarios. Implementation is written to make the
deterministic tests pass — never the other way around (no writing code first and
back-filling tests). Refactor only happens once the deterministic suite is green; a
refactor that breaks a deterministic test is a regression, full stop. A refactor that
changes a probabilistic eval score is reviewed against the threshold, not treated as a
binary pass/fail.

**Worked example (a) — new graph node** (e.g., `diagnose`):
1. *Spec:* add/extend the node's state-in/state-out contract in §5.1, and mark
   `side_effecting: bool` if relevant.
2. *Gherkin:* `features/diagnose_node.feature` — `Given` a state with `reranked_docs`
   and `relevance_grade` above threshold, `When` the `diagnose` node runs, `Then`
   `state.diagnosis` is populated and the next edge target is `propose_action`.
3. *PyTest:* unit test calls the node function directly with a fixture state and a
   mocked gateway client, asserts the output state keys and the routing decision —
   never asserts the diagnosis *text*.
4. *Implementation:* write the node to satisfy the test.
5. *Refactor:* internal prompt/logic can change freely as long as the state-shape
   contract test stays green; diagnosis quality is tracked separately in the eval gate
   (§8.2).

**Worked example (b) — new RAG retrieval step:**
1. *Spec:* amend Pillar 1 in §3 (e.g., new corpus, new top-k).
2. *Gherkin:* `Given` a query routed to `runbooks`, `When` retrieval runs, `Then` exactly
   `k=20` candidate docs are returned and each carries a `source` and `score` field —
   shape only, not relevance.
3. *PyTest:* mock the pgvector client and the `bge-reranker-base` call; assert call
   arguments (`k=20` in, `k=5` out) and required metadata fields.
4. *Implementation/Refactor:* as above. Whether the *right* docs come back is judged by
   `ragas context_precision` in the eval CI job (§8.2), not by this suite.

**Worked example (c) — new HITL interrupt point:**
1. *Spec:* add the new tool to the `side_effecting=True` set in §5.2/§3 Pillar 2.
2. *Gherkin* (tagged `@hitl`): `Given` a `proposed_action` with `side_effecting=True`,
   `When` the graph reaches `guardrail_output`, `Then` execution halts before `execute`
   and the checkpoint is persisted; `Given` a resumed thread with
   `human_decision.approved=true`, `Then` `execute` runs next; with
   `approved=false`, `Then` the graph returns to `diagnose`.
3. *PyTest:* integration test against a real (test-schema) `PostgresSaver` — invoke,
   assert the run is paused at `await_human_approval`, kill and re-instantiate the
   graph object (simulating a process restart), resume with a mocked decision, assert
   the correct next node ran. This is deterministic: it tests control flow, not
   judgment quality.
4. *Implementation/Refactor:* node wiring only; the human's actual decision-making is
   out of scope for tests by definition.

**Worked example (d) — new guardrail rule:**
1. *Spec:* add the rule/category to Pillar 3 in §3 (e.g., "flag credential-looking
   strings in alert text").
2. *Gherkin* (tagged `@guardrail`): `Given` `guardrail_check` returns a mocked `unsafe`
   verdict for the input, `When` `guardrail_input` runs, `Then` the graph routes to a
   `reject` node, not `router`.
3. *PyTest:* mock `guardrail_check` to return fixture verdicts (`safe`/`unsafe`/
   `borderline`); assert routing only. Whether Llama Guard *correctly* classifies real
   unsafe text is never asserted with `==` in this suite — see §8.2.
4. *Implementation/Refactor:* wiring and the stub-to-real swap (ADR-004) both go through
   this same loop; unstubbing only changes what's behind `guardrail_check`, not the
   test contract.

### 8.2 Two-tier testing model

**Deterministic Tier** — standard TDD, runs in every PyTest invocation and blocks merge
on failure. LLM/embedding/reranker calls are mocked or fixtured; nothing in this tier
is allowed to depend on a live model's actual output content.
- Graph structure and state-transition correctness (right keys, right shape)
- Conditional-edge routing *contracts* (the right node was selected — not whether the
  underlying reasoning was good)
- Schema validation (`IncidentState` TypedDict conformance)
- Guardrail *trigger* conditions (given a verdict, does the graph route correctly)
- HITL interrupt/resume mechanics, including checkpoint persistence across simulated
  restarts
- Gateway fallback/caching/rate-limit *behavior* (given a simulated provider timeout,
  does LiteLLM fail over; given a repeated request, is the cache hit)
- Fine-tuning pipeline *mechanics* (given mock LangSmith trace records, does the export
  script produce correctly-shaped contrastive JSONL pairs)

**Probabilistic Tier** — never asserted with `==`/`assert` in PyTest; lives only in the
eval harness (ragas / LangSmith LLM-as-judge), scored against a versioned threshold, run
as a separate CI quality gate that can fail a build without being a "failing test" in
the PyTest sense.
- RAG answer/diagnosis quality, groundedness, faithfulness (`ragas`)
- Routing *accuracy* (did the router pick the corpus a human would have picked) —
  distinct from routing *contract* above
- Self-RAG reflection quality (did the retry loop actually fetch better context)
- Guardrail moderation *accuracy* (does Llama Guard correctly flag real unsafe content)
  — distinct from guardrail *trigger wiring* above
- End-to-end remediation correctness (LangSmith rubric judge against
  `evals/golden_incidents.jsonl`)
- Fine-tuned embedding model performance vs. base model on golden-set retrieval metrics

**Pillar-to-tier mapping:**

| Pillar | Deterministic Tier covers | Probabilistic Tier covers |
|---|---|---|
| 1. Advanced RAG | retriever/reranker call contracts, routing edge selection | retrieval relevance, groundedness, self-RAG improvement |
| 2. HITL | interrupt trigger, checkpoint persistence, resume routing | n/a (human judgment is out of scope for both tiers) |
| 3. Guardrails | verdict-to-route wiring | actual moderation accuracy of Llama Guard |
| 4. Evals | dataset/schema validity, evaluator registration | the eval scores themselves (this pillar *is* the probabilistic tier's infrastructure) |
| 5. AI Gateway | fallback/caching/rate-limit logic | n/a (gateway behavior is deterministic by design) |
| 6. Fine-Tuning | export pipeline shape/correctness | fine-tuned vs. base model performance delta |

### 8.3 Gherkin conventions

- `@hitl` — any scenario exercising `interrupt()`/resume; must include both an
  `approved` and a `rejected` (or equivalent) example, never just the happy path.
- `@guardrail` — any scenario exercising `guardrail_check()` trigger wiring; verdicts
  are always supplied as mocked fixtures, never live model calls. Verdicts are
  strictly `safe`/`unsafe` (binary) per ADR-019/Feature 13. *(Corrected by
  ADR-019/Feature 13 — this originally listed a third "borderline" example value that
  no ADR ever implemented; v1's contract is binary only.)*
- `@gateway` — fallback, caching, and rate-limit scenarios against the LiteLLM proxy;
  provider failures are simulated, never real outages.
- `@eval-gated` — a marker, not a runnable PyTest-BDD scenario in the normal sense: it
  documents a behavior that is intentionally *not* asserted in Gherkin/PyTest and links
  to the corresponding entry in `evals/golden_incidents.jsonl` or the ragas metric name
  responsible for covering it. CI treats `@eval-gated` scenarios as skipped in the
  deterministic suite and checks instead that the linked eval exists and has a recorded
  threshold.
- Default (untagged) scenarios are deterministic-tier and must run fully mocked, with no
  network calls, in under the project's standard unit-test time budget.

### 8.4 LangSmith trace assertions in CI

**Asserted (build-blocking, structural):**
- Tool-call sequence matches the expected node order for the scenario (e.g.,
  `guardrail_input` precedes `router`; `await_human_approval` precedes `execute` for
  any `side_effecting` action) — read from the trace's span tree.
- Every model-call span carries gateway metadata (proxy host/route) — enforces
  ADR-003/ADR-006 are not silently bypassed.
- Per-node latency stays within a budget (e.g., retrieval span < 2s in CI's mocked
  environment) — catches accidental synchronous blocking calls.
- Token-count ceilings per call (cost guardrail) — catches prompt bloat regressions.

**Logged only, for human review (non-blocking):**
- The actual generated diagnosis text, proposed remediation rationale, and postmortem
  draft content.
- The LLM-as-judge's qualitative rationale string (the pass/fail *score* is
  build-blocking via §8.2; the rationale text is for a human to skim, not assert on).
- Full self-RAG retry transcripts (useful for debugging a flaky eval score, not for
  pass/fail).

### 8.5 Definition of Done

A feature is Done only when all of the following hold:
1. The relevant PMA section(s) (§3 and/or §5) are updated in the same PR as the code.
2. All Gherkin scenarios for the feature pass in the **Deterministic Tier** (PyTest-BDD/
   behave step defs, fully mocked) — including every `@hitl`/`@guardrail`/`@gateway`
   scenario's both-branches requirement (§8.3).
3. New or changed graph nodes have a unit test (state-transition contract) and, if they
   sit on a cycle or interrupt boundary, an integration test exercising that boundary
   against the real (test-schema) Postgres checkpointer.
4. If the feature touches a **Probabilistic Tier** surface (Pillars 1, 3-accuracy, or
   6), the relevant eval run meets or exceeds the previously recorded baseline score on
   `evals/golden_incidents.jsonl` — recorded as a new baseline in the Feature Log
   (§6), not just observed and discarded.
5. LangSmith structural assertions (§8.4) pass for the feature's scenarios.
6. The Feature Log (§6) has a row for the feature with its PMA-sections-touched filled
   in.

A feature that passes (2)-(3)-(5) but skips (4) when (4) applies is **not** Done — it is
a deterministic shell with unverified model behavior, which is the exact failure mode
ADR-005 was written to prevent.

---

## 9. Phase 4 Feature Roadmap (prioritized backlog)

Dependency-ordered per the graph skeleton (§5.2). Check an item off only once it has
passed the full Definition of Done (§8.5) and has a corresponding row in the Feature
Log (§6) linking to its `/memory/features/feature-N.md` detail file. Do not skip ahead
— each item assumes the ones above it exist.

- [ ] 1. Bootstrap local infra: docker-compose for Postgres+pgvector, Redis, and the
      LiteLLM proxy; implement `src/gateway/client_factory.py` as the only path to
      model clients; stub `guardrail_check()`; define the initial `IncidentState`
      schema and an empty graph with just `entry`→`END`.
- [ ] 2. Build the eval harness: author `evals/golden_incidents.jsonl` (20+ synthetic
      incidents with reference root cause, reference remediation, and pass/fail
      rubric), write `evals/judge_prompt.md`, and wire ragas (`context_precision`,
      `context_recall`, `faithfulness`) plus a LangSmith custom evaluator into CI.
- [ ] 3. Add the `guardrail_input` node: on graph entry, call `guardrail_check()` on
      the raw alert text and route to a `reject` node on an unsafe verdict, router
      otherwise.
- [ ] 4. Ingest runbooks, postmortems, and infra/code docs into pgvector, then add the
      `router` node that classifies the incoming query against those three corpora
      and selects a retriever.
- [ ] 5. Add the `retriever` and `reranker` nodes: pgvector similarity search at
      top-k=20 followed by `bge-reranker-base` cross-encoder re-ranking down to
      top-k=5.
- [ ] 6. Add the `grade_documents` node that scores reranked context for relevance
      and, on a low score, loops back to `router` with a reformulated query, capped
      at 2 retries.
- [ ] 7. Add the `diagnose` and `propose_action` nodes: generate a root-cause
      diagnosis from graded context, then produce a structured `{tool, args}`
      remediation proposal.
- [ ] 8. Add the `guardrail_output` node: run `guardrail_check()` on the proposed
      remediation explanation and route to `reject` on an unsafe verdict.
- [ ] 9. Add the `await_human_approval` interrupt node and wire `PostgresSaver` so any
      `side_effecting=True` proposed action pauses the graph durably until a human
      submits an `{approved, modified_action, note}` decision.
- [ ] 10. Add the `execute` node that runs the approved remediation against [mocked
      tool calls / a staging API — resolve Open Question #3 first], routing failures
      back to `diagnose` and successes to `write_postmortem`.
- [ ] 11. Add the `write_postmortem` node that drafts a postmortem from the diagnosis,
      action, and execution result, then passes it through `guardrail_output` before
      `END`.
- [ ] 12. Configure the LiteLLM proxy for production behavior: a primary→secondary
      fallback chain, Redis-backed semantic caching, and per-API-key rate limits, with
      cost/usage logging tagged to LangSmith `trace_id`.
- [ ] 13. Replace the `guardrail_check()` stub with real Llama Guard 3-8B inference
      behind the gateway, for both input and output moderation paths.
- [ ] 14. Build the fine-tuning pipeline: `scripts/export_finetune_pairs.py` exporting
      `grade_documents` LangSmith traces into contrastive JSONL pairs, a
      `sentence-transformers` fine-tune of `bge-small-en-v1.5`, and an A/B eval
      against the golden set before promoting it behind a config flag.
