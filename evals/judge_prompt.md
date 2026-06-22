<!--
Sentinel Remediation Judge — prompt template (ADR-008).

Rendered by src/evals/judge_prompt.py:render_judge_prompt(). The two tokens
{{QUESTIONS}} and {{JSON_SCHEMA}} are replaced programmatically — one yes/no
question per rubric criterion from the golden incident, and a JSON object
schema with exactly those criteria as boolean keys. Per ADR-008, the judge is
never asked for a 1-10 scale; every criterion is a binary true/false question,
and the aggregate pass/fail is "all criteria true" (computed by
src/evals/evaluator.py, not by the LLM).
-->

# Sentinel Remediation Judge

You are evaluating a proposed incident remediation against a reference answer
for a synthetic SRE incident. Answer strictly based on the material below —
do not use outside knowledge about the named services.

## Incident

- Alert: {{alert_text}}
- Reference root cause: {{reference_root_cause}}
- Reference remediation: {{reference_remediation}}

## Proposed answer under evaluation

- Diagnosis: {{proposed_diagnosis}}
- Proposed action: {{proposed_action}}

## Questions

Answer each question with `true` or `false` only. Do not use a 1-10 scale or
any other partial-credit scheme — every criterion is binary.

{{QUESTIONS}}

## Output format

Respond with a single JSON object and nothing else. It must have exactly these
boolean keys:

{{JSON_SCHEMA}}
