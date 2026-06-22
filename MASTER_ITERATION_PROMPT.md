# Master Iteration & Context Retrofit Prompt (Template)

> Reusable for every new feature. Copy this whole file, fill in the placeholders
> between `{{ }}`, attach the current `PROJECT_MEMORY.md`, and send.

---

Act as a Principal Software Architect and AI Engineer continuing the project documented
in the attached `PROJECT_MEMORY.md` (the "PMA"). Read the entire PMA — every ADR, every
Active Contract, the full Production RAG Blueprint, and the Development Workflow
Blueprint — before responding. Do not design anything until you have done this.

## Feature Request

```
{{FEATURE_REQUEST}}
```

(Describe the feature in plain language: what it does, what triggers it, what it
changes about existing behavior if anything.)

## Step 1 — Conflict Check (mandatory, before any design work)

Check `{{FEATURE_REQUEST}}` against every existing ADR and every entry in Active
Contracts (state schema, graph skeleton, gateway contract). For each ADR and each
contract, state explicitly: **"No conflict"** or **"Conflicts with ADR-NNN / Contract
§X because ___."** Do not skip any ADR or contract in this check, including ones that
seem obviously unrelated — state "No conflict" for those too, briefly.

## Step 2 — Branch on the Conflict Check

**If ANY conflict was found, this is a RETROFIT.** You must:
- Write a new ADR that explicitly supersedes the old one. Mark the old ADR's `Status`
  as `Superseded by ADR-NNN` — never delete or silently edit it.
- Enumerate every existing Gherkin feature file, PyTest module, and Active Contract
  section that breaks as a result, by name/path where known or by description if the
  exact path isn't in the PMA. For each, state what must change and why.
- This enumeration is the "blast radius" — it must be exhaustive, not illustrative.
  If you are not confident the list is complete, say so explicitly rather than
  presenting a partial list as final.
- Never change a contract's meaning without surfacing this list. If you find yourself
  about to redefine a state key, rename a node, or change a tier classification without
  writing a superseding ADR, stop and treat it as a retrofit instead.

**If NO conflict was found, this is ADDITIVE.** You must:
- Write a new ADR (numbered after the current highest ADR in the PMA) documenting the
  new decision(s), `Status: Accepted`.
- Design new Gherkin `.feature` content for the feature, following the tagging
  conventions in the Workflow Blueprint (`@hitl`, `@guardrail`, `@gateway`,
  `@eval-gated`, or untagged/deterministic).
- Design PyTest skeletons (test names + docstrings + assertions, not necessarily full
  implementations) for each scenario.

## Step 3 — Two-Tier Classification (required for both branches)

For every new or changed test you propose, classify it explicitly as **Deterministic
Tier** or **Probabilistic Tier** per the Workflow Blueprint's methodology. State the
classification next to each test, not just once at the top. If a test mixes both (e.g.,
asserts routing AND quality), split it into two tests rather than leaving it
ambiguous.

## Step 4 — Pillar Impact

State explicitly which of the six production pillars this feature touches, if any:

- [ ] 1. Advanced RAG Mechanics
- [ ] 2. Human-in-the-Loop
- [ ] 3. Guardrails
- [ ] 4. LLM Evals
- [ ] 5. AI Gateway
- [ ] 6. Fine-Tuning Integration

For every pillar checked, update that pillar's subsection in the Production RAG
Blueprint (§3) to reflect the implementation change — do not leave the master blueprint
stale while the detail lives only in the feature file.

## Step 5 — Feature Log Update

Add or update a row in the Feature Log (§6) of the master PMA:

| Feature ID | Description | Phase Introduced | Status | PMA Sections Touched |
|---|---|---|---|---|
| `{{FEATURE_ID}}` | `{{FEATURE_REQUEST short form}}` | `{{PHASE}}` | `In Progress` / `Done` | list every ADR/section number touched |

The Feature Log row links to a detail file at `/memory/features/{{FEATURE_ID}}.md` —
do NOT inline the full Gherkin scenarios or PyTest skeletons into the master PMA. The
master file stays a high-level index; full detail lives in the feature file.

## Step 6 — Required Output, in this exact order

**(a) The full updated master `PROJECT_MEMORY.md`.**
Every prior section reproduced in full, unchanged except for: any superseded ADR's
`Status` line, any new ADR appended, any pillar subsection updated per Step 4, and the
Feature Log row from Step 5. Do not summarize, truncate, or omit prior content. This
output replaces the master file.

**(b) The full new/updated `/memory/features/{{FEATURE_ID}}.md` detail file.**
Contains: the feature description, the Step 1 conflict check, the full Gherkin
`.feature` content, the full PyTest skeletons with tier classification per test, and
any retrofit blast-radius detail not already summarized in the master file's ADR.

**(c) A short "Blast Radius" summary.**
If this was additive, state "Additive — no existing contracts changed." If this was a
retrofit, list in plain bullets: which ADRs were superseded, which test/spec files
break, and the one-line reason each breaks. Keep this under ~150 words — it's a
heads-up, not a restatement of (a) and (b).

## Hard Rules

- Never silently redefine a contract. A redefinition without a superseding ADR is a
  bug in your output, not a valid shortcut.
- Never put a Probabilistic Tier behavior into a PyTest `assert ==`. Route it to an eval
  threshold instead, per the Workflow Blueprint.
- Never inline full feature-level detail into the master PMA — that's what the
  `/memory/features/` file is for.
- If the conflict check in Step 1 is ambiguous (you're not sure if something conflicts),
  say so explicitly and explain the ambiguity rather than guessing silently.
