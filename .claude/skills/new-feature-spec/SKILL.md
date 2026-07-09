---
name: new-feature-spec
description: Scaffold a new memory/features/feature-NN-*.md file following this repo's Conflict-Check/Gherkin/PyTest-skeleton/Definition-of-Done convention (docs/PROJECT_MEMORY.md §8.1). Use when starting work on a new feature, node, or capability for the Sentinel graph.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Bash(ls *)
  - Bash(grep *)
---

# /new-feature-spec — Scaffold a Feature Spec File

Per `CLAUDE.md`: "Per-feature specs (Conflict Check, Gherkin, PyTest skeletons,
Definition of Done) live in `memory/features/feature-NN-*.md`. These are not optional
housekeeping — the project's own workflow requires updating both files [this one and
`docs/PROJECT_MEMORY.md`] whenever an ADR or feature changes."

This skill only scaffolds the file's structure and pre-populates the mechanical parts
(next feature number, full current ADR list for the Conflict Check table, the
Definition of Done checklist verbatim from §8.5). It does **not** fill in the
substance — the actual conflict analysis, Gherkin scenarios, and PyTest bodies are
real work for whoever (human or Claude) writes the feature, done with the file open,
not guessed at scaffold time.

Arguments passed: `$ARGUMENTS` — treat as a short feature name/slug if given (e.g.
"rate limit dashboard node" -> slug `rate-limit-dashboard-node`). If empty, ask the
user for one before proceeding.

## Steps

### 1. Determine the next feature number

```bash
ls memory/features/ 2>/dev/null | grep -oE 'feature-[0-9]+' | grep -oE '[0-9]+' | sort -n | tail -1
```

Next number = that value + 1 (zero-padded to 2 digits, e.g. `16`). If the directory
is empty or missing, start at `01`.

### 2. Pull the current ADR list for the Conflict Check table

```bash
grep -n '^### ADR-' docs/PROJECT_MEMORY.md
```

Every ADR found here gets one row in the new file's Conflict Check table, in the
order they appear in the PMA (not necessarily numeric order — some ADRs were added
out of sequence, e.g. ADR-024 appears before ADR-023 in the current file). Each row's
verdict starts as a placeholder: `_TBD — review needed._` This is intentionally
exhaustive; skipping an ADR because it "obviously" doesn't apply is exactly the
mistake the Conflict Check step exists to catch (see feature-15's Conflict Check for
the level of specificity expected once filled in).

### 3. Determine the slug and title

From `$ARGUMENTS` or the user's answer, build:
- `SLUG`: lowercase, hyphenated, no special chars (e.g. `rate-limit-dashboard-node`)
- `TITLE`: human-readable title-case version for the H1

### 4. Write the file

Write `memory/features/feature-NN-SLUG.md` with this structure (substitute `NN`,
`SLUG`, `TITLE`, and the ADR table rows from step 2):

```markdown
# Feature NN — TITLE

**Phase introduced:** _TBD_
**Status:** Draft
**PMA sections touched:** _TBD — fill in once Step 1 below is complete (typically one
or more of §2 New ADR, §3 Pillar N, §6 Feature Log, §7 Open Questions, §9 roadmap item)_
**Source of truth:** _TBD — link the spec/plan doc this feature implements, if one
exists outside this file; otherwise delete this line._

## Feature Description

_TBD — one paragraph: what this feature adds/changes and why, in plain language._

## Step 1 — Conflict Check

| ADR / Contract | Verdict |
|---|---|
| ADR-001 | _TBD — review needed._ |
| ADR-002 | _TBD — review needed._ |
...(one row per ADR found in step 2, in file order)...
| §5.1 IncidentState schema | _TBD — review needed._ |
| §5.2 Graph skeleton | _TBD — review needed._ |
| §5.3 Gateway contract | _TBD — review needed._ |
| §8 Workflow Blueprint (BDD reality check) | _TBD — review needed._ |

**Verdict:** _TBD — ADDITIVE / CONFLICTING / AMENDS existing ADR-NNN, once every row
above is resolved, not before._

## New ADR

_TBD — if this feature requires a new architectural decision, draft it in
`docs/PROJECT_MEMORY.md` §2 first (see the `record-adr` skill), then link it here by
number. If no new ADR is needed, say so explicitly rather than leaving this blank._

## Blast Radius

_TBD — which existing tests could break, and what new test coverage is needed that
nothing existing provides. Distinguish "this regresses an existing guarantee" from
"this is new surface with no prior coverage to break."_

## Pillar Impact

- [ ] 1. Advanced RAG
- [ ] 2. HITL
- [ ] 3. Guardrails
- [ ] 4. Evals
- [ ] 5. AI Gateway
- [ ] 6. Fine-Tuning

## Gherkin

```gherkin
@TAG
Feature: TBD

  Scenario: TBD
    Given TBD
    When TBD
    Then TBD
```

## PyTest Skeletons (state which tier — Deterministic or Probabilistic, per §8.2 — and why)

```python
# tests/TBD/test_TBD.py

def test_TBD():
    """TBD"""
    ...
```

## Implementation Status

**Phase checklist:**
- [ ] TBD

**What was built so far:** _Nothing yet — spec only._

## Definition of Done

(Per `docs/PROJECT_MEMORY.md` §8.5 — a feature is Done only when all of these hold.)

- [ ] The relevant PMA section(s) (§3 and/or §5) are updated in the same PR as the code.
- [ ] All Gherkin scenarios pass in the Deterministic Tier, including every
      `@hitl`/`@guardrail`/`@gateway` scenario's both-branches requirement (§8.3).
- [ ] New or changed graph nodes have a unit test (state-transition contract) and,
      if they sit on a cycle or interrupt boundary, an integration test exercising
      that boundary against the real (test-schema) Postgres checkpointer.
- [ ] If this feature touches a Probabilistic Tier surface (Pillars 1, 3-accuracy, or
      6), the relevant eval run meets or exceeds the previously recorded baseline
      score on `evals/golden_incidents.jsonl`, recorded as a new baseline in the
      Feature Log (§6).
- [ ] LangSmith structural assertions (§8.4) pass for this feature's scenarios.
- [ ] The Feature Log (§6) has a row for this feature with its PMA-sections-touched
      filled in.
```

### 5. Report back

Tell the user the file path written, the feature number assigned, and remind them of
the two follow-up edits this spec-driven workflow requires once the spec is filled in:
1. `docs/PROJECT_MEMORY.md` §6 Feature Log — new row.
2. `docs/PROJECT_MEMORY.md` §9 Phase 4 Feature Roadmap — new item, if this is
   roadmap-tracked work (not all features are — feature-15 was explicitly
   post-roadmap).

Do not make those two edits automatically — they describe what was *actually built*,
which doesn't exist yet at scaffold time.
