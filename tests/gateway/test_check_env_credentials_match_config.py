"""Deterministic Tier — docs/LLM_AGNOSTICISM_REVIEW.md §1.4/Item 3: keeps
`scripts/check_env.sh`'s `REQUIRED_VARS` honest against
`infra/litellm_config.yaml`'s `model_list`, the same way
`test_litellm_config_yaml.py` keeps code-referenced aliases honest against
declared ones.

These are two independently hand-maintained lists today: `litellm_config.yaml`
names a real provider for each alias via its `model:` prefix (`openai/...`,
`together_ai/...`, `ollama_chat/...`); `check_env.sh` separately lists which
env vars must be set before `make up`/`smoke`/`test`/`shell` will proceed.
ADR-023 (Feature 15) had to edit both by hand in lockstep when it dropped
`ANTHROPIC_API_KEY`/`COHERE_API_KEY` — nothing mechanically checked that edit
was complete. This test is that mechanical check: it would catch a future
config edit that starts requiring a new provider's credential without anyone
remembering to also update `check_env.sh` (or the reverse — a stale required
var nobody removed after a provider was dropped)."""

import re
import unittest
from pathlib import Path

import yaml

from src.gateway.litellm_proxy import DEFAULT_CONFIG_PATH

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CHECK_ENV_PATH = _REPO_ROOT / "scripts" / "check_env.sh"

#: Maps a `litellm_params.model`'s provider prefix to the env var LiteLLM
#: needs to actually reach that provider. A prefix absent from this dict is
#: assumed to need no credential (true for `ollama`/`ollama_chat`, which
#: authenticate via `OLLAMA_BASE_URL`, not an API key) — add a new provider
#: here the same day it's added to litellm_config.yaml, not after.
#: `together_ai` removed (ADR-023 Phase 5, 2026-07-06): sentinel-guardrail
#: migrated to ollama_chat/llama-guard3:8b; TOGETHERAI_API_KEY no longer required.
_PROVIDER_PREFIX_TO_REQUIRED_VAR = {
    "openai": "OPENAI_API_KEY",
}

_REQUIRED_VARS_PATTERN = re.compile(r"REQUIRED_VARS=\(([^)]*)\)")


def _provider_prefix(model: str) -> str:
    return model.split("/", 1)[0]


def _expected_required_vars(model_list: list[dict]) -> set[str]:
    expected = set()
    for entry in model_list:
        prefix = _provider_prefix(entry["litellm_params"]["model"])
        if prefix in _PROVIDER_PREFIX_TO_REQUIRED_VAR:
            expected.add(_PROVIDER_PREFIX_TO_REQUIRED_VAR[prefix])
    return expected


def _actual_required_vars(check_env_text: str) -> set[str]:
    match = _REQUIRED_VARS_PATTERN.search(check_env_text)
    if not match:
        raise AssertionError(
            f"could not find a REQUIRED_VARS=(...) array in {CHECK_ENV_PATH}"
        )
    return set(match.group(1).split())


class CheckEnvCredentialsMatchConfigTests(unittest.TestCase):
    def setUp(self):
        self.raw = yaml.safe_load(Path(DEFAULT_CONFIG_PATH).read_text())

    def test_check_env_required_vars_exactly_match_providers_used_in_config(self):
        expected = _expected_required_vars(self.raw["model_list"])
        actual = _actual_required_vars(CHECK_ENV_PATH.read_text())

        missing_from_check_env = expected - actual
        stale_in_check_env = actual - expected

        self.assertFalse(
            missing_from_check_env,
            f"litellm_config.yaml references a provider needing {missing_from_check_env!r}, "
            "but scripts/check_env.sh's REQUIRED_VARS does not check for it",
        )
        self.assertFalse(
            stale_in_check_env,
            f"scripts/check_env.sh's REQUIRED_VARS still requires {stale_in_check_env!r}, "
            "but no model_list entry in litellm_config.yaml uses that provider anymore",
        )


if __name__ == "__main__":
    unittest.main()
