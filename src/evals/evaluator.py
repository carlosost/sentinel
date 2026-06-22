"""sentinel_remediation_judge — the end-to-end LLM-as-judge evaluator (ADR-008).

Registered under a stable name in the LangSmith registry shim
(src/evals/langsmith_registry.py — see that module's docstring for why it's a
shim, not the real langsmith package, in this sandbox).

The judge's own LLM call is constructed via client_factory.get_chat_client(),
never a direct provider SDK import — this is the same gateway requirement
every other model call in the project follows (ADR-003/006), and it applies to
the eval harness itself, not just graph nodes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

from src.evals.judge_prompt import render_judge_prompt
from src.evals.langsmith_registry import registry
from src.gateway.client_factory import get_chat_client

EVALUATOR_NAME = "sentinel_remediation_judge"


def run_judge(
    incident: Dict[str, Any],
    proposed: Optional[Dict[str, Any]] = None,
    *,
    template_path: Optional[Union[Path, str]] = None,
) -> Dict[str, Any]:
    """Run the remediation judge against one golden incident.

    Returns {"incident_id", "criteria": {criterion: bool, ...}, "passed": bool}.
    `passed` is True only if every rubric criterion came back true — aggregation
    is done here in Python, never delegated to the LLM (ADR-008: no 1-10 scale,
    no LLM-computed aggregate).
    """
    kwargs = {} if template_path is None else {"template_path": template_path}
    prompt = render_judge_prompt(incident, proposed, **kwargs)

    client = get_chat_client(model="sentinel-judge")
    raw_response = client.invoke(prompt)
    verdicts = json.loads(raw_response)

    criteria_names = [item["criterion"] for item in incident["rubric"]]
    missing = [c for c in criteria_names if c not in verdicts]
    if missing:
        raise ValueError(f"judge response missing criteria: {missing}")

    passed = all(verdicts[c] is True for c in criteria_names)
    return {
        "incident_id": incident["incident_id"],
        "criteria": {c: verdicts[c] for c in criteria_names},
        "passed": passed,
    }


# Registered at import time, mirroring how a real langsmith evaluator
# registration call would run once at module load.
registry.register_evaluator(EVALUATOR_NAME, run_judge)
