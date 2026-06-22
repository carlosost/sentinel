"""Deterministic Tier — ADR-006's enforcement mechanism must itself pass on a clean
repo, and must actually be able to fail (tested via a synthetic fixture tree) so it
isn't a lint rule that silently never fires.

Fixture trees are built under a `tempfile.TemporaryDirectory()` (sandbox-local /tmp,
not this mounted workspace) and passed to the script's optional target-dir argument
— never written into the real repo. An earlier version of this test wrote directly
into src/ and tried to delete the file afterward; the workspace mount does not
permit unlinking files it didn't create, which left two orphaned stub files in
src/ (tmp6i7_b1m5.py, tmph94x_g5b.py). This rewrite avoids that failure mode
entirely."""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LINT_SCRIPT = REPO_ROOT / "scripts" / "lint_gateway_usage.sh"


class LintGatewayUsageTests(unittest.TestCase):
    def test_lint_script_is_executable_and_passes_on_clean_repo(self):
        self.assertTrue(LINT_SCRIPT.exists())
        mode = os.stat(LINT_SCRIPT).st_mode
        self.assertTrue(mode & stat.S_IXUSR, "lint script must be executable")
        result = subprocess.run(
            ["bash", str(LINT_SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_lint_script_fails_on_a_direct_provider_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "src").mkdir()
            (tmp_path / "src" / "gateway").mkdir()
            (tmp_path / "src" / "bad_node.py").write_text("import openai\n")
            result = subprocess.run(
                ["bash", str(LINT_SCRIPT), str(tmp_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("openai", result.stdout)

    def test_lint_script_ignores_violations_inside_gateway_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "src" / "gateway").mkdir(parents=True)
            (tmp_path / "src" / "gateway" / "client_factory.py").write_text(
                "from langchain_openai import ChatOpenAI\n"
            )
            result = subprocess.run(
                ["bash", str(LINT_SCRIPT), str(tmp_path)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
