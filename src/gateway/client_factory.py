"""
Sole construction path for every LLM/embedding client in the codebase.

ADR-003: the LiteLLM Proxy sits in front of every model call. ADR-006: a CI lint
(scripts/lint_gateway_usage.sh) rejects any direct `openai`/`anthropic` import or
client construction outside this module. Every node, eval script, and guardrail
check must obtain its client from here — never from a provider SDK directly.

ADR-018 (Feature 12) layers production behavior (fallback chains, semantic caching,
per-key rate limits) on top of this via named model aliases configured in
`infra/litellm_config.yaml`; this module only needs to know the alias name, not the
underlying provider model.

SANDBOX NOTE (ADR-021): this dev sandbox has no PyPI egress, so `langchain_openai`
is not installable here. `_ChatClient`/`_EmbeddingClient` below are minimal stdlib
stand-ins that preserve the public shape callers depend on (`.model_name`/`.model`,
`.openai_api_base`). They are a temporary substitution, not a redesign — Open
Question #15 tracks swapping them for the real `ChatOpenAI`/`OpenAIEmbeddings` once
this runs somewhere with real package access, with a parity check to confirm the
swap is a no-op for every call site.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from src.observability.tracing import get_current_trace_id

#: Read once per process; tests override via monkeypatch/env, never by importing a
#: provider SDK directly.
_DEFAULT_PROXY_URL_ENV = "LITELLM_PROXY_URL"
_DEFAULT_API_KEY_ENV = "LITELLM_VIRTUAL_KEY"


class GatewayConfigError(RuntimeError):
    """Raised when the gateway is asked to construct a client without configuration."""


@dataclass
class _ChatClient:
    """Stand-in for `langchain_openai.ChatOpenAI` (ADR-021). Exposes the subset of
    the real client's surface that Sentinel's nodes currently depend on."""

    model_name: str
    base_url: str
    api_key: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def openai_api_base(self) -> str:
        return self.base_url

    def invoke(self, *_args, **_kwargs):  # pragma: no cover - exercised once real client lands
        raise NotImplementedError(
            "Real model invocation requires langchain_openai (Open Question #15); "
            "not available in this sandbox."
        )


@dataclass
class _EmbeddingClient:
    """Stand-in for `langchain_openai.OpenAIEmbeddings` (ADR-021)."""

    model: str
    base_url: str
    api_key: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def openai_api_base(self) -> str:
        return self.base_url

    def embed_documents(self, *_args, **_kwargs):  # pragma: no cover
        raise NotImplementedError(
            "Real embedding calls require langchain_openai (Open Question #15); "
            "not available in this sandbox."
        )


def _proxy_base_url() -> str:
    base_url = os.environ.get(_DEFAULT_PROXY_URL_ENV)
    if not base_url:
        raise GatewayConfigError(
            f"{_DEFAULT_PROXY_URL_ENV} is not set. Every model client must be "
            "constructed against the LiteLLM proxy (ADR-003) — there is no fallback "
            "to a direct provider endpoint."
        )
    return base_url


def _virtual_key() -> Optional[str]:
    # Per ADR-018, the caller is expected to select a virtual key (sentinel-app,
    # sentinel-eval, sentinel-dev) appropriate to the calling context. Falling back
    # to None lets local/dev usage proceed without one configured yet.
    return os.environ.get(_DEFAULT_API_KEY_ENV)


def _with_trace_metadata(kwargs: dict[str, Any]) -> dict[str, Any]:
    """ADR-018: every gateway request carries `metadata={"trace_id": ...}` from
    the active LangSmith run (`src.observability.tracing`), so the proxy's
    cost/usage logs can be joined against LangSmith traces (Project Charter
    success criterion 4). A caller-supplied `metadata` dict is merged with,
    not overwritten by, the trace_id — `trace_id` itself is never clobbered by
    a caller's own metadata key of the same name, since this is the one
    contract ADR-018 pins. Outside any traced run, `trace_id` is simply
    `None` — never an error (see `get_current_trace_id`'s docstring)."""
    metadata = dict(kwargs.get("metadata") or {})
    metadata.setdefault("trace_id", get_current_trace_id())
    return {**kwargs, "metadata": metadata}


def get_chat_client(model: str, **kwargs) -> _ChatClient:
    """Construct a chat-completion client routed through the LiteLLM proxy.

    Args:
        model: a model *alias* name (e.g. "sentinel-chat", "sentinel-guardrail"),
            resolved to a real provider model + fallback chain by
            `infra/litellm_config.yaml` (ADR-018) — never a raw provider model
            string passed straight to a provider SDK.
        **kwargs: forwarded to the underlying client (e.g. `temperature`,
            `cache={"no-cache": True}` for the eval-determinism carve-out).
    """
    return _ChatClient(
        model_name=model,
        base_url=_proxy_base_url(),
        api_key=_virtual_key() or "unset",
        extra=_with_trace_metadata(kwargs),
    )


def get_embedding_client(model: str, **kwargs) -> _EmbeddingClient:
    """Construct an embedding client routed through the LiteLLM proxy.

    Args:
        model: a model alias name (e.g. "sentinel-embedding"). See `get_chat_client`.
    """
    return _EmbeddingClient(
        model=model,
        base_url=_proxy_base_url(),
        api_key=_virtual_key() or "unset",
        extra=_with_trace_metadata(kwargs),
    )
