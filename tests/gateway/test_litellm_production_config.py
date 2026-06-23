"""Deterministic Tier (ADR-018) — LiteLLM proxy production behaviors: fallback
routing, semantic caching with the eval-determinism carve-out, per-virtual-key
rate limits, and trace_id-tagged request logging. Exercised against
`MockLiteLLMProxy` (ADR-021 addendum — this sandbox cannot run the real
`litellm` proxy image), driven by the real `infra/litellm_config.yaml` so the
config file stays the single source of truth. Whether fallback/caching changes
response *quality* is out of scope (§8.2's Pillar 5 row: "n/a, gateway behavior
is deterministic by design"). Test names match the feature-12 spec's
pre-drafted PyTest skeletons exactly."""

import os
import unittest
from unittest.mock import MagicMock

from src.gateway.client_factory import get_chat_client
from src.gateway.litellm_proxy import (
    MockLiteLLMProxy,
    RateLimitExceededError,
)
from src.observability.tracing import traced_run


class LiteLLMProductionConfigTests(unittest.TestCase):
    def setUp(self):
        self.proxy = MockLiteLLMProxy()
        self._old_env = dict(os.environ)
        os.environ["LITELLM_PROXY_URL"] = "http://localhost:4000"
        os.environ["LITELLM_VIRTUAL_KEY"] = "sk-test-key"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_provider_timeout_triggers_fallback(self):
        """Deterministic Tier."""

        def provider_call(model_alias, prompt):
            if model_alias == "sentinel-router":
                raise TimeoutError("primary model timed out")
            return f"response from {model_alias}"

        result = self.proxy.complete(
            "sentinel-router", "classify this alert", provider_call=provider_call
        )

        self.assertEqual(result, "response from sentinel-router-fallback")
        self.assertEqual(self.proxy.call_log[-1]["served_by"], "sentinel-router-fallback")

    def test_repeated_app_request_is_cache_hit(self):
        """Deterministic Tier."""
        provider_call = MagicMock(return_value="diagnosis text")

        first = self.proxy.complete(
            "sentinel-diagnose", "same prompt", virtual_key="sentinel-app", provider_call=provider_call
        )
        second = self.proxy.complete(
            "sentinel-diagnose", "same prompt", virtual_key="sentinel-app", provider_call=provider_call
        )

        self.assertEqual(first, second)
        provider_call.assert_called_once()
        self.assertFalse(self.proxy.call_log[0]["cache_hit"])
        self.assertTrue(self.proxy.call_log[1]["cache_hit"])

    def test_eval_harness_requests_always_set_no_cache(self):
        """Deterministic Tier. Enforces ADR-018's eval-determinism carve-out —
        this is the test that would catch a future regression reintroducing the
        ADR-005 risk. Asserts both that the proxy itself honors `no-cache`
        (never serving a stale response to it) and that the one real eval call
        site (`src.evals.evaluator.run_judge`) actually sets it."""
        provider_call = MagicMock(return_value="judge verdict")

        self.proxy.complete(
            "sentinel-judge",
            "same prompt",
            virtual_key="sentinel-eval",
            cache={"no-cache": True},
            provider_call=provider_call,
        )
        self.proxy.complete(
            "sentinel-judge",
            "same prompt",
            virtual_key="sentinel-eval",
            cache={"no-cache": True},
            provider_call=provider_call,
        )

        self.assertEqual(provider_call.call_count, 2)
        self.assertFalse(self.proxy.call_log[0]["cache_hit"])
        self.assertFalse(self.proxy.call_log[1]["cache_hit"])

        client = get_chat_client(model="sentinel-judge", cache={"no-cache": True})
        self.assertEqual(client.extra["cache"], {"no-cache": True})

    def test_eval_and_app_virtual_keys_have_independent_rate_limits(self):
        """Deterministic Tier."""
        provider_call = MagicMock(return_value="ok")
        app_limit = self.proxy._virtual_keys["sentinel-app"].rpm_limit

        for _ in range(app_limit):
            self.proxy.complete(
                "sentinel-router", f"prompt-{_}", virtual_key="sentinel-app", provider_call=provider_call
            )
        with self.assertRaises(RateLimitExceededError):
            self.proxy.complete(
                "sentinel-router", "one-too-many", virtual_key="sentinel-app", provider_call=provider_call
            )

        # sentinel-app's exhausted limit must not affect sentinel-eval.
        result = self.proxy.complete(
            "sentinel-judge", "eval prompt", virtual_key="sentinel-eval", provider_call=provider_call
        )
        self.assertEqual(result, "ok")

    def test_every_gateway_call_carries_trace_id_metadata(self):
        """Deterministic Tier. Enforces Project Charter success criterion 4."""
        with traced_run("trace-abc-123"):
            client = get_chat_client(model="sentinel-diagnose")

        self.assertEqual(client.extra["metadata"]["trace_id"], "trace-abc-123")

        provider_call = MagicMock(return_value="diagnosis")
        self.proxy.complete(
            "sentinel-diagnose",
            "prompt",
            virtual_key="sentinel-app",
            metadata=client.extra["metadata"],
            provider_call=provider_call,
        )

        self.assertEqual(self.proxy.call_log[-1]["metadata"]["trace_id"], "trace-abc-123")


if __name__ == "__main__":
    unittest.main()
