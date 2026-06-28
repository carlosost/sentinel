"""Deterministic Tier (ADR-018) — `infra/litellm_config.yaml` structural
contract in isolation: every model alias actually referenced by `model=...`
anywhere under src/*.py or scripts/*.sh must be declared with a fallback, and
all three virtual keys (ADR-018) must exist with a positive rate limit. This
is the static counterpart to test_litellm_production_config.py's behavioral
tests — it would catch a future node OR script adding a new
`get_chat_client(model=...)` alias without a matching config entry, without
needing to run the proxy at all.

Widened 2026-06-28 (post-ADR-023 usage review) to also scan scripts/*.sh: the
original src/*.py-only scan missed scripts/entrypoint.sh's smoke-check
heredoc, which referenced a `sentinel-chat` alias that was never declared in
litellm_config.yaml's model_list — a real, previously-undetected gap. See
memory/features/feature-12-litellm-proxy-hardening.md's dated note and
LITELLM_USAGE_REVIEW.md for the full story."""

import re
import unittest
from pathlib import Path

import yaml

from src.gateway.litellm_proxy import DEFAULT_CONFIG_PATH

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = _REPO_ROOT / "src"
SCRIPTS_ROOT = _REPO_ROOT / "scripts"

_ALIAS_CALL_PATTERN = re.compile(r'model=["\'](sentinel-[a-z-]+)["\']')

#: (root, glob) pairs to scan for `model="sentinel-*"` call sites. `src/*.py` is
#: real node/eval code; `scripts/*.sh` covers shell-embedded Python like
#: `scripts/entrypoint.sh`'s smoke-check heredoc, which is invisible to a
#: `*.py`-only glob despite constructing a real gateway client. A
#: `sentinel-chat` alias referenced only in entrypoint.sh's heredoc (not a real
#: model_list entry) went undetected by this test until this widened scan
#: caught it — see feature-12-litellm-proxy-hardening.md's dated note.
_SCAN_TARGETS = [
    (SRC_ROOT, "*.py"),
    (SCRIPTS_ROOT, "*.sh"),
]


def _aliases_referenced_in_source() -> set[str]:
    aliases = set()
    for root, glob in _SCAN_TARGETS:
        for path in root.rglob(glob):
            if "__pycache__" in path.parts:
                continue
            aliases.update(_ALIAS_CALL_PATTERN.findall(path.read_text()))
    return aliases


class LiteLLMConfigYamlTests(unittest.TestCase):
    def setUp(self):
        self.raw = yaml.safe_load(Path(DEFAULT_CONFIG_PATH).read_text())

    def test_every_alias_referenced_in_code_is_declared_with_a_fallback(self):
        declared = {entry["model_name"]: entry["litellm_params"] for entry in self.raw["model_list"]}
        referenced = _aliases_referenced_in_source()
        self.assertTrue(referenced, "expected at least one sentinel-* alias call site")

        for alias in referenced:
            self.assertIn(alias, declared, f"{alias!r} is called in code but missing from model_list")
            self.assertTrue(
                declared[alias].get("fallbacks"),
                f"{alias!r} has no configured fallback (ADR-018)",
            )

    def test_three_virtual_keys_exist_with_positive_rate_limits(self):
        virtual_keys = {
            entry["key_alias"]: entry for entry in self.raw["general_settings"]["virtual_keys"]
        }
        self.assertEqual(set(virtual_keys), {"sentinel-app", "sentinel-eval", "sentinel-dev"})
        for key_alias, entry in virtual_keys.items():
            self.assertGreater(entry["rpm_limit"], 0, f"{key_alias!r} has a non-positive rpm_limit")
            self.assertGreater(entry["max_budget"], 0, f"{key_alias!r} has a non-positive max_budget")

    def test_semantic_caching_is_enabled(self):
        self.assertTrue(self.raw["litellm_settings"]["cache"])
        self.assertEqual(self.raw["litellm_settings"]["cache_params"]["type"], "redis")


if __name__ == "__main__":
    unittest.main()
