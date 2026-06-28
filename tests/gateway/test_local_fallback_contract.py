"""Probabilistic Tier (ADR-005/008's classification) — exercises the real local
Ollama-served fallback models through a real LiteLLM proxy, never mocked.
Companion to `tests/gateway/test_litellm_production_config.py`'s
`MockLiteLLMProxy`-backed Deterministic Tier tests, which assert fallback
*mechanics* (does failover happen, is it logged) without ever calling a real
model. These tests assert fallback *output quality*: does the real local model's
response still satisfy the contract a calling node expects.

ADR-023 (Feature 15, Phase 3). Gherkin source: the `@gateway @fallback`-tagged
scenarios appended to `memory/features/feature-12-litellm-proxy-hardening.md`.

SANDBOX NOTE: this dev sandbox has neither a running `ollama` service nor a
running `litellm` proxy (no Docker/network egress — ADR-021's standing
constraint). Every test below probes `LITELLM_PROXY_URL` for reachability in
`setUpClass` and skips with a printed reason if it's unreachable — the same
"never silently pass, never silently skip without saying why" discipline
`scripts/ingest_corpora.py` and `scripts/run_eval.py`-style harnesses already
use elsewhere in this project for sandbox-unavailable dependencies. This is the
first time that reachability-probe pattern is expressed as an actual
`unittest` skip condition rather than a script-level `try/except` — recorded
here, not assumed to already exist.

Run for real once `make up pull-local-models` has been run against a machine
with Docker:
    LITELLM_PROXY_URL=http://localhost:4000 python3 -m unittest \
        tests.gateway.test_local_fallback_contract -v
"""

from __future__ import annotations

import json
import os
import socket
import unittest
from urllib.parse import urlparse

from src.retrieval.vector_search import EmbeddingDimensionMismatchError, search
from src.ingestion.document_store import InMemoryDocumentStore

PROXY_URL_ENV = "LITELLM_PROXY_URL"


def _proxy_reachable() -> bool:
    """Best-effort TCP-connect probe — deliberately not a full HTTP health
    check (no `requests` dependency confirmed available everywhere this might
    run). A closed/refused connection or any error means "not reachable"; this
    function never raises."""
    base_url = os.environ.get(PROXY_URL_ENV)
    if not base_url:
        return False
    parsed = urlparse(base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


@unittest.skipUnless(
    _proxy_reachable(),
    f"No reachable LiteLLM proxy at ${{{PROXY_URL_ENV}}} — these tests require "
    "a real `make up pull-local-models` stack (Docker), not available in this "
    "sandbox. Skipped, not silently passed (ADR-021 discipline).",
)
class LocalFallbackContractTests(unittest.TestCase):
    """Requires a real LiteLLM proxy fronting a real Ollama instance with the
    three models from `scripts/pull_local_models.sh` already pulled."""

    def test_router_fallback_returns_valid_route_json(self):
        """Calls sentinel-router-fallback directly (bypassing the primary),
        asserts the response still satisfies router.py's exact contract:
        {"route": "<one of runbooks|postmortems|infra_code_docs>"}, no prose."""
        import httpx  # local import: only required when this test actually runs

        base_url = os.environ[PROXY_URL_ENV]
        resp = httpx.post(
            f"{base_url}/chat/completions",
            json={
                "model": "sentinel-router-fallback",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Classify this alert into exactly one corpus: "
                            'runbooks, postmortems, or infra_code_docs. Respond '
                            'as JSON: {"route": "<corpus>"}.\n\nAlert: disk usage '
                            "at 95% on db-primary-3"
                        ),
                    }
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)  # must be valid JSON, no markdown fencing
        self.assertIn("route", parsed)
        self.assertIn(parsed["route"], {"runbooks", "postmortems", "infra_code_docs"})

    def test_diagnose_fallback_returns_parseable_json(self):
        """Same pattern for the Tier-2 model — most likely to regress, since
        Tier-2 prompts are longer/more open-ended than router's three-way
        classification."""
        import httpx

        base_url = os.environ[PROXY_URL_ENV]
        resp = httpx.post(
            f"{base_url}/chat/completions",
            json={
                "model": "sentinel-diagnose-fallback",
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Given this alert and retrieved runbook excerpt, "
                            'respond as JSON: {"diagnosis": "<short string>"}.\n\n'
                            "Alert: disk usage at 95% on db-primary-3\nRunbook: "
                            "rotate logs and vacuum old WAL segments when disk "
                            "usage exceeds 90%."
                        ),
                    }
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=90.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        self.assertIn("diagnosis", parsed)
        self.assertIsInstance(parsed["diagnosis"], str)
        self.assertTrue(parsed["diagnosis"].strip())

    def test_embedding_fallback_returns_correct_dimensionality(self):
        """bge-m3 (1024-dim) and text-embedding-3-small (1536-dim) do NOT
        share an embedding dimension. This test does not assert they match —
        it asserts Open Question #16's resolution end-to-end: comparing a
        real bge-m3-produced vector against a corpus row embedded at 1536-dim
        raises `EmbeddingDimensionMismatchError`, the named hard-failure this
        project chose over silent truncation/padding or a per-dimension index
        (see `src/retrieval/vector_search.py`'s docstring on that class)."""
        import httpx

        base_url = os.environ[PROXY_URL_ENV]
        resp = httpx.post(
            f"{base_url}/embeddings",
            json={"model": "sentinel-embedding-fallback", "input": ["disk usage alert"]},
            timeout=60.0,
        )
        resp.raise_for_status()
        bge_m3_vector = resp.json()["data"][0]["embedding"]
        self.assertEqual(
            len(bge_m3_vector),
            1024,
            "bge-m3 is expected to return 1024-dim embeddings; if this "
            "changed, Open Question #16's resolution needs re-checking.",
        )

        store = InMemoryDocumentStore()
        store.upsert(
            corpus="runbooks",
            content="rotate logs when disk usage exceeds 90%",
            embedding=[0.0] * 1536,  # stand-in for a real text-embedding-3-small row
        )

        with self.assertRaises(EmbeddingDimensionMismatchError):
            search(store, "runbooks", bge_m3_vector, k=20)


if __name__ == "__main__":
    unittest.main()
