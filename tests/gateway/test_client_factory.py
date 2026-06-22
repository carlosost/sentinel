"""Deterministic Tier — enforces ADR-003/006/007: every client is constructed only
through client_factory, pointed at the LiteLLM proxy. No live network call is made.

Uses stdlib `unittest` (ADR-021 sandbox note: no PyPI egress here for pytest)."""

import os
import unittest

from src.gateway.client_factory import GatewayConfigError, get_chat_client, get_embedding_client


class ClientFactoryTests(unittest.TestCase):
    def setUp(self):
        self._old_env = dict(os.environ)
        os.environ["LITELLM_PROXY_URL"] = "http://localhost:4000"
        os.environ["LITELLM_VIRTUAL_KEY"] = "sk-test-key"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_get_chat_client_points_at_the_proxy(self):
        client = get_chat_client(model="sentinel-chat")
        self.assertEqual(client.openai_api_base, "http://localhost:4000")
        self.assertEqual(client.model_name, "sentinel-chat")

    def test_get_embedding_client_points_at_the_proxy(self):
        client = get_embedding_client(model="sentinel-embedding")
        self.assertEqual(client.openai_api_base, "http://localhost:4000")
        self.assertEqual(client.model, "sentinel-embedding")

    def test_missing_proxy_url_raises_gateway_config_error(self):
        del os.environ["LITELLM_PROXY_URL"]
        with self.assertRaises(GatewayConfigError):
            get_chat_client(model="sentinel-chat")

    def test_missing_virtual_key_does_not_raise(self):
        # A virtual key is expected (ADR-018) but its absence must not crash
        # local/dev usage before keys are provisioned.
        del os.environ["LITELLM_VIRTUAL_KEY"]
        client = get_chat_client(model="sentinel-chat")
        self.assertIsNotNone(client)


if __name__ == "__main__":
    unittest.main()
