"""Deterministic Tier — router classification mechanics only (ADR-010); never
asserts whether the chosen corpus was the 'correct' one for a given query —
that's routing *accuracy*, Probabilistic Tier per §8.2."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.graph.nodes.router import RouterError, VALID_ROUTES, router


def _state(raw_alert: str = "disk usage at 95% on db-primary") -> dict:
    return {"raw_alert": raw_alert}


class RouterNodeTests(unittest.TestCase):
    @patch("src.graph.nodes.router.get_chat_client")
    def test_router_writes_single_route_value(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"route": "postmortems"})
        mock_get_chat_client.return_value = mock_client

        update = router(_state())

        self.assertEqual(update["route"], "postmortems")
        self.assertEqual(set(update.keys()), {"route"})

    @patch("src.graph.nodes.router.get_chat_client")
    def test_router_uses_client_factory(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"route": "runbooks"})
        mock_get_chat_client.return_value = mock_client

        router(_state())

        mock_get_chat_client.assert_called_once_with(model="sentinel-router")
        mock_client.invoke.assert_called_once()

    @patch("src.graph.nodes.router.get_chat_client")
    def test_router_accepts_every_valid_route(self, mock_get_chat_client):
        for route in VALID_ROUTES:
            mock_client = MagicMock()
            mock_client.invoke.return_value = json.dumps({"route": route})
            mock_get_chat_client.return_value = mock_client

            update = router(_state())

            self.assertEqual(update["route"], route)

    @patch("src.graph.nodes.router.get_chat_client")
    def test_router_raises_on_invalid_route(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"route": "not_a_real_corpus"})
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(RouterError):
            router(_state())

    @patch("src.graph.nodes.router.get_chat_client")
    def test_router_raises_on_missing_route_key(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = json.dumps({"not_route": "runbooks"})
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(RouterError):
            router(_state())

    @patch("src.graph.nodes.router.get_chat_client")
    def test_router_raises_on_non_json_response(self, mock_get_chat_client):
        mock_client = MagicMock()
        mock_client.invoke.return_value = "not json at all"
        mock_get_chat_client.return_value = mock_client

        with self.assertRaises(RouterError):
            router(_state())


if __name__ == "__main__":
    unittest.main()
