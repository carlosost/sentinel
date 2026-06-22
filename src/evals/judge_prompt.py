"""Renders evals/judge_prompt.md against a golden incident (ADR-008).

Stdlib-only string templating (no Jinja2 in requirements.txt) — the template
uses {{token}} placeholders and this module does a literal substitution pass,
plus a generated block for the per-criterion questions and JSON schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "evals" / "judge_prompt.md"


def _format_remediation(remediation: Dict[str, Any]) -> str:
    tool = remediation.get("tool", "?")
    args = remediation.get("args", {})
    args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{tool}({args_str})"


def render_judge_prompt(
    incident: Dict[str, Any],
    proposed: Optional[Dict[str, Any]] = None,
    *,
    template_path: Union[Path, str] = DEFAULT_TEMPLATE_PATH,
) -> str:
    """Render the judge prompt for one golden incident.

    `proposed` is the candidate answer under evaluation — `{"diagnosis": ...,
    "proposed_action": ...}`. It is optional and defaults to placeholders,
    since this feature (Feature 02) builds the harness before any graph node
    produces real diagnoses (see Feature 02's "Pillar Impact" caveat).
    """
    template = Path(template_path).read_text(encoding="utf-8")
    proposed = proposed or {}

    rubric = incident["rubric"]
    questions_lines = []
    schema_lines = []
    for i, item in enumerate(rubric, start=1):
        criterion = item["criterion"]
        description = item["description"]
        questions_lines.append(f"{i}. {description} (criterion: `{criterion}`)")
        schema_lines.append(f'  "{criterion}": true|false')

    questions_block = "\n".join(questions_lines)
    schema_block = "{\n" + ",\n".join(schema_lines) + "\n}"

    rendered = template
    rendered = rendered.replace("{{alert_text}}", incident["alert_text"])
    rendered = rendered.replace("{{reference_root_cause}}", incident["reference_root_cause"])
    rendered = rendered.replace(
        "{{reference_remediation}}", _format_remediation(incident["reference_remediation"])
    )
    rendered = rendered.replace(
        "{{proposed_diagnosis}}", proposed.get("diagnosis", "(not yet available)")
    )
    rendered = rendered.replace(
        "{{proposed_action}}", proposed.get("proposed_action", "(not yet available)")
    )
    rendered = rendered.replace("{{QUESTIONS}}", questions_block)
    rendered = rendered.replace("{{JSON_SCHEMA}}", schema_block)
    return rendered
