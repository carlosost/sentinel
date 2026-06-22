# Meta-Framework: Building a Production-Grade LLM Application

A strategy document for mastering LangChain, LangGraph, LangSmith, and Advanced RAG through a single cumulative project, governed by Spec-Driven Development, BDD, and TDD.

---

## 1. Strategic Overview

The project is executed in **4 phases**. Phases 1–3 are one-time setup phases that produce and refine a single cumulative artifact — the **Project Memory Asset (PMA)**. Phase 4 is not a one-time event: it's the repeating loop (one cycle per feature) that you run for the rest of the project's life, each time invoking the **Master Iteration & Context Retrofit Prompt** produced in Phase 3.

| Phase | Purpose | Frequency |
|---|---|---|
| 1 — Ideation & Scope | Define the project, force in all 6 production pillars architecturally | Once |
| 2 — Methodology Synthesis | Define the Spec → BDD → TDD loop and how it interacts with non-deterministic LLM components | Once |
| 3 — Meta-Prompting Blueprint | Produce the reusable per-feature prompt template | Once |
| 4 — Feature Implementation Loop | Run the Phase 3 prompt once per feature, retrofitting the PMA each time | Repeated, N times |

The PMA is the spine of the whole system. Every phase reads it, amends it, and re-emits it in full. Nothing is "remembered" by you or by the model across sessions except what's written into that file — treat any decision not captured there as a decision that will be silently lost.

---

## 2. Structural Critique of Your Proposed Plan

Three things in the original plan will cause real pain if left as-is. Fixing them now is cheaper than retrofitting later.

**The AI Gateway and Guardrails are listed as pillars #3 and #5, but they are not features — they are infrastructure that every other pillar depends on.** If you build the LangGraph agent first and bolt LiteLLM (gateway) and input/output moderation on afterward, you have to retrofit every single model-binding call and every entry/exit node in the graph, which will break already-passing BDD scenarios that assumed raw, unmoderated, ungated I/O. The fix: in Phase 1, the Tech Stack section must commit to routing 100% of model calls through the gateway from the first line of code, and the graph's entry/exit nodes must be designed with guardrail hooks from day one — even if the actual guardrail logic is a stub initially. Pillars 3 and 5 are load-bearing walls, not rooms added later.

**TDD and LLM non-determinism are in direct tension, and your plan doesn't yet separate what TDD/BDD can validate from what only Evals can validate.** Strict red-green-refactor assumes a deterministic assertion. An LLM's RAG answer, routing decision, or generated text is probabilistic — asserting `response == expected_string` is a flaky test waiting to happen. The fix is a two-tier testing model, made explicit in Phase 2: (a) **Deterministic Tier** — graph structure, state transitions, schema validation, guardrail trigger conditions, routing *contracts* (does it call the right node, not whether the LLM's reasoning was "good") — these are TDD'd normally, with the LLM call mocked or replaced by a fixture. (b) **Probabilistic Tier** — RAG answer quality, routing accuracy, groundedness — these are never asserted in PyTest; they live exclusively in the Evals pillar (ragas / LangSmith LLM-as-judge) and are tracked as a quality score over a threshold, not a pass/fail unit test. Conflating these two tiers is the single most common failure mode in "TDD for LLM apps" attempts.

**HITL requires a persistence layer, and that's an architectural decision, not an implementation detail you can decide later.** LangGraph's interrupt/resume mechanism for HITL requires a checkpointer (state must survive the wait for human approval, potentially across process restarts). If this isn't decided in Phase 1 (e.g., SQLite checkpointer for dev, Postgres for "prod"), you'll discover it mid-build when the first approval-gated tool call needs to pause and resume, and retrofitting persistence into an already-running graph is a bigger rewrite than it sounds.

A fourth, smaller risk: **the PMA itself will become unbounded.** A single monolithic markdown file that grows by a full ADR set on every feature will eventually become too large to usefully inject as context. The fix, built into the Phase 3 template: the PMA stays as a compact **master index + decision log** (architecture, stack, active contracts, ADR summaries), while verbose per-feature specs/Gherkin/test plans live in linked sibling files (`/memory/features/feature-N.md`). The master file references them by name; it never inlines them in full after the project grows past a handful of features.

---

## 3. Project Memory Asset — Required Structure

Every phase prompt below instructs the model to read this structure, update it, and re-emit it in full (or, post-Phase-4-scale, emit the master index plus the new/changed feature file). Sections:

1. **Project Charter** — problem statement, why it requires LangGraph/cyclic state, success criteria
2. **Architecture Decision Records (ADRs)** — numbered, append-only, each with Context / Decision / Consequences / Status (Active/Superseded)
3. **Production RAG Blueprint** — how each of the 6 pillars is realized, with the specific library/pattern chosen for each
4. **Tech Stack** — pinned choices and why
5. **Development Workflow Blueprint** (added in Phase 2) — the Spec→BDD→TDD loop, the two-tier testing model
6. **Active Contracts** — current API/state schemas, graph node signatures, anything a new feature must not silently break
7. **Feature Log** — table of features built so far, status, link to their detail file
8. **Open Questions / Risks**

---

## 4. Phase 1 Prompt — Ideation, Tech Stack, & Production RAG Scope

Copy this verbatim into a new session (no prior PMA exists yet, so this prompt creates it).

```markdown
Act as a Principal Software Architect and AI Engineer. I am building a production-grade
LLM application from scratch in Python to master LangChain, LangGraph, LangSmith, and
Advanced RAG, governed by Spec-Driven Development, BDD, and TDD.

TASK: Define the initial PROJECT IDEA and produce the first version of our "Project
Memory Asset" (PMA) — the single cumulative markdown document that will track every
architectural decision for the life of this project.

HARD CONSTRAINTS on the project idea:
- Must inherently require LangGraph (a cyclic, multi-step state machine — not a linear
  chain). Justify why a simple chain would NOT suffice.
- Must inherently require LangSmith for tracing and evaluation.
- Must explicitly architect for all 6 of the following pillars, naming the specific
  library/pattern for each (do not leave any as "TBD"):
    1. Advanced RAG mechanics (query routing, re-ranking, self-RAG/reflection)
    2. Human-in-the-Loop state management (LangGraph interrupt/resume, with a named
       checkpointer/persistence choice — this cannot be deferred)
    3. Guardrails for input/output moderation (name the library)
    4. LLM Evals (automated eval dataset strategy + ragas or LangSmith judge approach)
    5. AI Gateway for fallback/caching/rate-limiting (name the library, e.g. LiteLLM)
    6. Fine-tuning integration (what gets fine-tuned — a small embedding or routing
       model, not the main LLM — and what LangSmith trace data feeds it)

CRITICAL ARCHITECTURAL RULE: Pillars 3 (Guardrails) and 5 (AI Gateway) are
infrastructure, not features. Specify in the Tech Stack that ALL model calls are routed
through the gateway and ALL graph entry/exit nodes have guardrail hooks from the first
line of code — even if guardrail logic starts as a stub. Do not let me defer this.

DELIVERABLE — output the full Project Memory Asset in markdown with these sections:
1. Project Charter (problem statement, why LangGraph/cyclic state is required, success
   criteria)
2. Architecture Decision Records — ADR-001 onward, each with Context / Decision /
   Consequences / Status
3. Production RAG Blueprint — one subsection per pillar (1–6 above), each naming the
   exact library/pattern and where it sits in the graph
4. Tech Stack — pinned library choices and the one-line reason for each
5. Active Contracts (initial state schema / graph skeleton, even if minimal)
6. Feature Log (empty table, ready for Phase 4)
7. Open Questions / Risks

Before finalizing, explicitly challenge your own proposed architecture for at least one
structural flaw (e.g., a pillar that's been bolted on rather than designed in,
a missing persistence decision, an evals strategy that's untestable) and resolve it
in the output rather than just flagging it.

Output ONLY the markdown PMA. This file will be saved as `PROJECT_MEMORY.md` and fed
back to you in every subsequent phase — write it as a standalone document a future
session can fully reconstruct context from.
```

---

## 5. Phase 2 Prompt — Methodology Synthesis & Workflow Engine

Run this after Phase 1, with the PMA from Phase 1 pasted in or attached.

```markdown
Act as a Principal Software Architect and AI Engineer continuing the project documented
in the attached PROJECT_MEMORY.md. Read it fully before responding — do not propose
anything that contradicts an existing ADR; if you believe one should change, raise it
as a new ADR that supersedes the old one (mark the old one's Status as "Superseded").

TASK: Define the Development Workflow Blueprint — exactly how Spec-Driven Development,
BDD, and TDD interact for THIS project's stack, and append it to the PMA as a new
top-level section.

REQUIRED CONTENT:
1. The loop, stated precisely: API/Schema Spec -> Gherkin (.feature) files -> PyTest
   unit & integration tests -> implementation -> refactor. Show how this loop applies
   to: (a) a new graph node, (b) a new RAG retrieval step, (c) a new HITL interrupt
   point, (d) a guardrail rule.
2. A TWO-TIER TESTING MODEL, made explicit, because LLM output is non-deterministic and
   naive TDD will produce flaky tests:
   - Deterministic Tier (PyTest, TDD'd normally, LLM calls mocked/fixtured): graph
     structure, state transitions, schema validation, guardrail trigger conditions,
     routing CONTRACTS (the right node is called — not whether the reasoning was good),
     gateway fallback behavior.
   - Probabilistic Tier (never asserted with == in PyTest; lives only in Evals): RAG
     answer quality, routing accuracy, groundedness, faithfulness — tracked via ragas /
     LangSmith LLM-as-judge as a score against a threshold, run in CI as a quality gate
     separate from the unit test suite.
   State explicitly which of the 6 production pillars' behaviors fall into each tier.
3. Gherkin conventions for this project specifically (tagging scheme for HITL scenarios,
   guardrail-rejection scenarios, eval-gated scenarios).
4. How LangSmith tracing plugs into CI: what gets asserted from a trace (e.g., token
   counts, tool-call sequences, latency budgets) vs. what only gets logged for human
   review.
5. Definition of Done for a feature — must reference both tiers explicitly.

DELIVERABLE: Output the ENTIRE updated PROJECT_MEMORY.md — every prior section
unchanged unless you are explicitly superseding an ADR, plus the new "Development
Workflow Blueprint" section appended. Do not summarize or omit prior content. This
output replaces the PMA file in full.

[PASTE OR ATTACH CURRENT PROJECT_MEMORY.md HERE]
```

---

## 6. Phase 3 Deliverable — The Master Iteration & Context Retrofit Prompt

This is the template you'll reuse for every feature, forever (Phase 4 = running this repeatedly). Generate it once by running the prompt below; then save the *output* as your reusable template.

**Prompt to generate the template:**

```markdown
Act as a Principal Software Architect continuing the project in the attached
PROJECT_MEMORY.md. 

TASK: Design and output the "Master Iteration & Context Retrofit Prompt" — a reusable
markdown prompt template (not project-specific content, a TEMPLATE with placeholders)
that I will fill in and re-run once per new feature for the rest of this project.

The template must enforce this exact sequence every time it's used:
1. Require the full current PROJECT_MEMORY.md to be attached/pasted, and instruct the
   model to read it completely before responding.
2. Take a feature description placeholder (e.g., "{{FEATURE_REQUEST}}").
3. Instruct the model to check the feature request against EVERY existing ADR and
   Active Contract for conflicts BEFORE designing anything new.
4. If a conflict exists: instruct the model to propose a RETROFIT — a new ADR that
   supersedes the old one, plus an explicit list of which existing tests/specs/Gherkin
   files break and how they must change. The model must never silently change a
   contract without surfacing the blast radius.
5. If no conflict exists: instruct the model to design the feature additively (new ADR,
   new Gherkin feature file content, new PyTest skeletons per the two-tier model from
   the Workflow Blueprint).
6. Require the model to classify every new test it proposes as Deterministic Tier or
   Probabilistic Tier per our existing methodology, and to flag if a pillar (RAG
   mechanics / HITL / Guardrails / Evals / Gateway / Fine-tuning) is touched, updating
   that pillar's subsection in the Production RAG Blueprint if its implementation
   changed.
7. Require the model to update the Feature Log table (status + link to a new
   `/memory/features/feature-N.md` detail file rather than inlining full Gherkin/test
   content into the master file, to keep the PMA from growing unbounded).
8. Require the model to output, in this order: (a) the full updated master
   PROJECT_MEMORY.md, (b) the new/updated `/memory/features/feature-N.md` detail file in
   full, (c) a short "Blast Radius" summary of anything retrofitted.

Output ONLY the reusable template, written so I can copy it fresh for every feature and
just fill in the placeholders.

[PASTE OR ATTACH CURRENT PROJECT_MEMORY.md HERE]
```

The model's output from this prompt is the artifact you keep and reuse — fill in `{{FEATURE_REQUEST}}` and re-attach the latest `PROJECT_MEMORY.md` every time you start a new feature.

---

## 7. Phase 4 — The Feature Implementation Loop (how this actually runs)

Phase 4 isn't a prompt you write once — it's the operating rhythm for the rest of the build:

1. Pick the next feature (e.g., "add self-RAG reflection to the retrieval node," "add an approval gate before the refund tool fires").
2. Fill in the Phase 3 template's `{{FEATURE_REQUEST}}` placeholder, attach the current `PROJECT_MEMORY.md`, run it.
3. Take the output: write the Gherkin feature file, write the failing PyTest skeletons (both tiers), implement until green, run the eval suite for anything in the Probabilistic Tier, confirm it clears threshold.
4. Save the updated `PROJECT_MEMORY.md` and the new feature detail file — these become the input to step 2 of the *next* feature.
5. Repeat. Each cycle is a closed loop: nothing is lost, every contract change is visible, and the Memory Asset is always the single source of truth for "what is this system right now."
