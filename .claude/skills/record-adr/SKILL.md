---
name: record-adr
description: Append a new numbered Architecture Decision Record to docs/PROJECT_MEMORY.md §2 in this repo's established format. Use when a structural/architectural decision has been made that needs to be recorded — CLAUDE.md requires every ADR to live in this one master file.
user-invocable: true
allowed-tools:
  - Read
  - Edit
  - Bash(grep *)
---

# /record-adr — Append a New ADR to the PMA

Per `CLAUDE.md`: "`docs/PROJECT_MEMORY.md` is the master reference. Every Architecture
Decision Record (ADR) lives there. Read it before making any structural change."

This skill only appends a correctly-formatted, next-numbered ADR entry. It does not
invent the decision's content — that must come from the user or from Claude's own
analysis of the change already made/being made. If the substance isn't known yet,
stop and ask rather than writing a placeholder ADR that looks finished but isn't.

Arguments passed: `$ARGUMENTS` — treat as a short title for the decision if given.

## Steps

### 1. Find the next ADR number

```bash
grep -oE '^### ADR-[0-9]+' docs/PROJECT_MEMORY.md | grep -oE '[0-9]+' | sort -n | tail -1
```

Next number = that value + 1, zero-padded to 3 digits (e.g. `025`). Note this repo's
ADRs are **not** always inserted in strict ascending file order (ADR-024 currently
appears before ADR-023) — always pick next-number by the highest number seen, not by
file position, and insert the new entry at the **end** of §2 (Architecture Decision
Records), immediately before the next `## ` (level-2) heading.

### 2. Confirm section boundaries

```bash
grep -n '^## ' docs/PROJECT_MEMORY.md
```

§2 "Architecture Decision Records" runs from its own heading to the next `## `
heading (currently §3 "Production RAG Blueprint"). The new ADR entry goes at the end
of that range.

### 3. Gather the decision's content

Read the diff or ask the user for:
- **Title** — one line, matching the pattern `ADR-NNN: <short decision statement>
  (Feature XX[, resolves Open Question #N][, retrofit])`. The parenthetical feature
  reference is a strong repo convention — check `memory/features/` for the feature
  this decision belongs to, or ask if it's not yet spec'd (in which case, consider
  running `new-feature-spec` first).
- **Context** — what problem/gap forced this decision.
- **Decision** — the actual choice, as concrete bullet points (shapes, field names,
  scope boundaries — see existing ADRs like ADR-015/ADR-016 for the level of
  specificity expected). Sub-bullets are normal and encouraged for multi-part
  decisions.
- **Consequences** — what this unblocks or constrains going forward.
- **Status** — `Accepted` unless the user says otherwise (`Proposed`, `Superseded by
  ADR-NNN`, etc.)
- **Implementation status** (optional) — only add this sub-section if the decision
  was scoped differently than actually built (sandbox substitutions, deferred scope,
  etc.) — see ADR-016's "Implementation status (Feature 10)" for the pattern. Skip
  this entirely if implementation matched the decision exactly.

### 4. Append the entry

Insert immediately before §3's heading, in this exact shape:

```markdown
### ADR-NNN: TITLE
- **Context:** ...
- **Decision:**
  - ...
- **Consequences:** ...
- **Status:** Accepted.
```

Add a blank line before and after to match the existing spacing between ADR entries.

### 5. Cross-link, don't duplicate

- If a `memory/features/feature-NN-*.md` file exists for this decision, update its
  "New ADR" section to point at the new number (per that file's own convention —
  "See ADR-NNN in `docs/PROJECT_MEMORY.md` §2... Not restated here").
- Do **not** copy the ADR's content into the feature file — this repo's explicit
  convention is that ADRs live in exactly one place.
- If this ADR resolves an Open Question from §7, note that in the title's
  parenthetical (`resolves Open Question #N`) and flag to the user that §7 should be
  updated separately (this skill does not edit §7 automatically — Open Question
  resolutions often need their own nuanced note, as seen in ADR-023/Open Question #17's
  "closed as moot" resolution, not a mechanical fill-in).

### 6. Report back

State the ADR number assigned and remind the user of the other PMA sections this
decision likely touches (§6 Feature Log's "PMA Sections Touched" column, and §7 if an
Open Question is resolved) — these are separate edits, not made automatically here.
