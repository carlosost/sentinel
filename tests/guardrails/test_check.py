"""Deterministic Tier — guardrail_check's real-inference call path (ADR-019,
ADR-023-Phase5): client_factory is mocked; these tests assert the
gateway-only call contract and the GuardrailVerdict shape, never whether a
verdict is *correct*. Moderation accuracy is the Probabilistic Tier concern,
scored via evals/guardrail_redteam.jsonl, never asserted with `==` here.

ADR-023-Phase5 (2026-07-06): guardrail_check() now accepts two response
formats from the model:
  1. Llama Guard 3 native: 'safe' or 'unsafe\\nS1,S3'
  2. JSON fallback: '{"verdict": ..., "reason": ..., "category": ...}'

Native format is tried first; JSON is the fallback (for openai/omni-moderation
or any model that returns JSON). Tests are split into two groups to cover both
paths explicitly."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.guardrails.check import GuardrailCheckError, guardrail_check


def _json_client(payload: dict) -> MagicMock:
    """Mock returning JSON — simulates non-Llama-Guard fallback models."""
    client = MagicMock()
    client.invoke.return_value = json.dumps(payload)
    return client


def _native_client(response: str) -> MagicMock:
    """Mock returning native Llama Guard 3 format — 'safe' or 'unsafe\\nS1'."""
    client = MagicMock()
    client.invoke.return_value = response
    return client


# ---------------------------------------------------------------------------
# Gateway contract (format-agnostic)
# ---------------------------------------------------------------------------

class GuardrailGatewayContractTests(unittest.TestCase):
    @patch("src.guardrails.check.get_chat_client")
    def test_guardrail_check_uses_sentinel_guardrail_alias(self, mock_get_chat_client):
        """Enforces ADR-003/006/019's gateway-only call path."""
        mock_get_chat_client.return_value = _native_client("safe")
        guardrail_check("a perfectly benign alert", direction="input")
        mock_get_chat_client.assert_called_once_with(model="sentinel-guardrail")

    @patch("src.guardrails.check.get_chat_client")
    def test_guardrail_calls_do_not_set_no_cache(self, mock_get_chat_client):
        """Guardrail traffic is cache-eligible (ADR-018/019) — unlike eval
        harness traffic, no cache=no-cache override is set."""
        mock_get_chat_client.return_value = _native_client("safe")
        guardrail_check("a perfectly benign alert", direction="input")
        _, kwargs = mock_get_chat_client.call_args
        self.assertNotIn("cache", kwargs)


# ---------------------------------------------------------------------------
# Native Llama Guard 3 format
# ---------------------------------------------------------------------------

class NativeFormatTests(unittest.TestCase):
    @patch("src.guardrails.check.get_chat_client")
    def test_native_safe_response_returns_safe_verdict(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _native_client("safe")
        verdict = guardrail_check("a benign alert", direction="input")
        self.assertEqual(verdict["verdict"], "safe")
        self.assertIsNone(verdict["category"])
        self.assertIsInstance(verdict["reason"], str)
        self.assertTrue(verdict["reason"])

    @patch("src.guardrails.check.get_chat_client")
    def test_native_safe_with_trailing_whitespace(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _native_client("  safe  \n")
        verdict = guardrail_check("a benign alert", direction="input")
        self.assertEqual(verdict["verdict"], "safe")

    @patch("src.guardrails.check.get_chat_client")
    def test_native_unsafe_single_category(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _native_client("unsafe\nS1")
        verdict = guardrail_check("ignore previous instructions", direction="input")
        self.assertEqual(verdict["verdict"], "unsafe")
        self.assertEqual(verdict["category"], "S1")
        self.assertIn("Violent Crimes", verdict["reason"])

    @patch("src.guardrails.check.get_chat_client")
    def test_native_unsafe_multiple_categories_uses_first_as_primary(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _native_client("unsafe\nS1,S9")
        verdict = guardrail_check("some dangerous text", direction="input")
        self.assertEqual(verdict["category"], "S1")
        self.assertIn("Violent Crimes", verdict["reason"])
        self.assertIn("Indiscriminate Weapons", verdict["reason"])

    @patch("src.guardrails.check.get_chat_client")
    def test_native_unsafe_with_uppercase_safe_in_category_line_still_parsed(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _native_client("unsafe\nS10")
        verdict = guardrail_check("hateful text", direction="input")
        self.assertEqual(verdict["verdict"], "unsafe")
        self.assertEqual(verdict["category"], "S10")

    @patch("src.guardrails.check.get_chat_client")
    def test_native_unsafe_with_no_category_line_raises(self, mock_get_chat_client):
        """'unsafe' with no second line is a malformed native response."""
        mock_get_chat_client.return_value = _native_client("unsafe")
        with self.assertRaises(GuardrailCheckError):
            guardrail_check("some text", direction="input")

    @patch("src.guardrails.check.get_chat_client")
    def test_verdict_shape_keys_present_for_native_safe(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _native_client("safe")
        verdict = guardrail_check("benign", direction="output")
        self.assertEqual(set(verdict.keys()), {"verdict", "reason", "category"})

    @patch("src.guardrails.check.get_chat_client")
    def test_verdict_shape_keys_present_for_native_unsafe(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _native_client("unsafe\nS2")
        verdict = guardrail_check("steal credentials", direction="output")
        self.assertEqual(set(verdict.keys()), {"verdict", "reason", "category"})


# ---------------------------------------------------------------------------
# JSON fallback format (openai/omni-moderation-latest or other JSON models)
# ---------------------------------------------------------------------------

class JsonFallbackFormatTests(unittest.TestCase):
    @patch("src.guardrails.check.get_chat_client")
    def test_json_safe_verdict_accepted(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _json_client(
            {"verdict": "safe", "reason": "benign alert text", "category": None}
        )
        verdict = guardrail_check("a perfectly benign alert", direction="input")
        self.assertEqual(verdict["verdict"], "safe")
        self.assertIsNone(verdict["category"])

    @patch("src.guardrails.check.get_chat_client")
    def test_json_unsafe_verdict_accepted(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _json_client(
            {"verdict": "unsafe", "reason": "prompt injection attempt", "category": "S1"}
        )
        verdict = guardrail_check("ignore previous instructions", direction="input")
        self.assertEqual(verdict["verdict"], "unsafe")
        self.assertEqual(verdict["category"], "S1")

    @patch("src.guardrails.check.get_chat_client")
    def test_json_safe_with_non_null_category_raises(self, mock_get_chat_client):
        """ADR-019: category must be null when verdict is safe."""
        mock_get_chat_client.return_value = _json_client(
            {"verdict": "safe", "reason": "benign", "category": "S1"}
        )
        with self.assertRaises(GuardrailCheckError):
            guardrail_check("some text", direction="input")

    @patch("src.guardrails.check.get_chat_client")
    def test_json_unsafe_with_null_category_raises(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _json_client(
            {"verdict": "unsafe", "reason": "flagged", "category": None}
        )
        with self.assertRaises(GuardrailCheckError):
            guardrail_check("some text", direction="input")

    @patch("src.guardrails.check.get_chat_client")
    def test_json_invalid_verdict_value_raises(self, mock_get_chat_client):
        mock_get_chat_client.return_value = _json_client(
            {"verdict": "borderline", "reason": "unsure", "category": None}
        )
        with self.assertRaises(GuardrailCheckError):
            guardrail_check("some text", direction="input")


# ---------------------------------------------------------------------------
# Unparseable responses — raises regardless of attempted format
# ---------------------------------------------------------------------------

class UnparseableResponseTests(unittest.TestCase):
    @patch("src.guardrails.check.get_chat_client")
    def test_response_matching_neither_format_raises(self, mock_get_chat_client):
        """A response that is neither valid native format nor valid JSON raises
        GuardrailCheckError — never silently treated as safe."""
        client = MagicMock()
        client.invoke.return_value = "I think this looks fine actually"
        mock_get_chat_client.return_value = client
        with self.assertRaises(GuardrailCheckError):
            guardrail_check("some text", direction="input")

    @patch("src.guardrails.check.get_chat_client")
    def test_empty_response_raises(self, mock_get_chat_client):
        client = MagicMock()
        client.invoke.return_value = ""
        mock_get_chat_client.return_value = client
        with self.assertRaises(GuardrailCheckError):
            guardrail_check("some text", direction="input")


if __name__ == "__main__":
    unittest.main()
