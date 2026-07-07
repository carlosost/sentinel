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

ADR-024 (Production Readiness): `get_chat_client`/`get_embedding_client` now return
real `langchain_openai.ChatOpenAI`/`OpenAIEmbeddings` when the package is available,
falling back to the `_ChatClient`/`_EmbeddingClient` stdlib shims (ADR-021) when it
is not. The shims are kept as fallback so `make test-local` continues to pass in
environments without PyPI access — the conditional import pattern makes the upgrade
transparent: installing `langchain-openai` is the only action required to activate
the real clients, with no code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from src.observability.tracing import get_current_trace_id

# Real langchain_openai clients — used when the package is installed.
# Falls back to stdlib shims (ADR-021) when not available, so this module
# can be imported in environments without PyPI access (e.g. the dev sandbox).
try:
    from langchain_openai import ChatOpenAI as _RealChatClient
    from langchain_openai import OpenAIEmbeddings as _RealEmbeddingClient
    _LANGCHAIN_OPENAI_AVAILABLE = True
except ImportError:
    _LANGCHAIN_OPENAI_AVAILABLE = False


class _ContentUnwrappingChatClient:
    """Thin wrapper around the real ChatOpenAI that unwraps AIMessage → str.

    Every node in this codebase was written against the stdlib shim's
    `.invoke()` contract, which returned a plain string. The real
    `langchain_openai.ChatOpenAI.invoke()` returns an `AIMessage` object.
    Rather than touching every node, this wrapper extracts `.content` so the
    rest of the codebase sees the same string interface it always has.
    """

    def __init__(self, client) -> None:
        self._client = client

    def invoke(self, *args, **kwargs) -> str:
        result = self._client.invoke(*args, **kwargs)
        return result.content if hasattr(result, "content") else str(result)

    # Forward attribute access for introspection (e.g. model_name, openai_api_base).
    def __getattr__(self, name: str):
        return getattr(self._client, name)

#: Read once per process; tests override via monkeypatch/env, never by importing a
#: provider SDK directly.
_DEFAULT_PROXY_URL_ENV = "LITELLM_PROXY_URL"
_DEFAULT_API_KEY_ENV = "LITELLM_VIRTUAL_KEY"


class GatewayConfigError(RuntimeError):
    """Raised when the gateway is asked to construct a client without configuration."""


@dataclass
class _ChatClient:
    """Stdlib fallback for `langchain_openai.ChatOpenAI` (ADR-021). Active only when
    langchain_openai is not installed. Exposes the same public surface the real
    client does (`.model_name`, `.openai_api_base`, `.invoke()`); `.invoke()` raises
    NotImplementedError until the real package is present."""

    model_name: str
    base_url: str
    api_key: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def openai_api_base(self) -> str:
        return self.base_url

    def invoke(self, *_args, **_kwargs):  # pragma: no cover
        raise NotImplementedError(
            "Real model invocation requires langchain_openai; install it via "
            "`pip install -r requirements.txt` (ADR-024 / Open Question #15)."
        )


@dataclass
class _EmbeddingClient:
    """Stdlib fallback for `langchain_openai.OpenAIEmbeddings` (ADR-021)."""

    model: str
    base_url: str
    api_key: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def openai_api_base(self) -> str:
        return self.base_url

    def embed_documents(self, *_args, **_kwargs):  # pragma: no cover
        raise NotImplementedError(
            "Real embedding calls require langchain_openai; install it via "
            "`pip install -r requirements.txt` (ADR-024 / Open Question #15)."
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


def get_chat_client(model: str, **kwargs):
    """Construct a chat-completion client routed through the LiteLLM proxy.

    Returns a real `langchain_openai.ChatOpenAI` when the package is installed,
    or a `_ChatClient` stdlib shim otherwise (ADR-021/ADR-024).

    Args:
        model: a model *alias* name (e.g. "sentinel-router", "sentinel-guardrail"),
            resolved to a real provider model + fallback chain by
            `infra/litellm_config.yaml` (ADR-018) — never a raw provider model
            string passed straight to a provider SDK.
        **kwargs: forwarded to the underlying client (e.g. `temperature`,
            `cache={"no-cache": True}` for the eval-determinism carve-out).
    """
    extra = _with_trace_metadata(kwargs)
    if _LANGCHAIN_OPENAI_AVAILABLE:
        return _ContentUnwrappingChatClient(
            _RealChatClient(
                model=model,
                openai_api_base=_proxy_base_url(),
                openai_api_key=_virtual_key() or "unset",
                **extra,
            )
        )
    return _ChatClient(
        model_name=model,
        base_url=_proxy_base_url(),
        api_key=_virtual_key() or "unset",
        extra=extra,
    )


def get_embedding_client(model: str, **kwargs):
    """Construct an embedding client routed through the LiteLLM proxy.

    Returns a real `langchain_openai.OpenAIEmbeddings` when the package is
    installed, or a `_EmbeddingClient` stdlib shim otherwise (ADR-021/ADR-024).

    Args:
        model: a model alias name (e.g. "sentinel-embedding"). See `get_chat_client`.
    """
    extra = _with_trace_metadata(kwargs)
    if _LANGCHAIN_OPENAI_AVAILABLE:
        # Two things stripped / overridden for OpenAIEmbeddings:
        #
        # 1. `metadata` — not forwarded by OpenAIEmbeddings to Embeddings.create();
        #    it lands in model_kwargs and surfaces as a TypeError at call time.
        #    Strip it here; trace IDs are still captured by LangSmith's
        #    auto-instrumentation on the surrounding traced_run() context.
        #
        # 2. `check_embedding_ctx_length=False` — OpenAIEmbeddings uses tiktoken
        #    to count tokens before sending the request. tiktoken doesn't know
        #    LiteLLM alias names (e.g. "sentinel-embedding") and tries to fetch
        #    the cl100k_base vocab file from the internet, which fails in air-gapped
        #    or rate-limited environments. Disabling the check skips tiktoken
        #    entirely; LiteLLM's proxy enforces the real model's context limit.
        embedding_extra = {k: v for k, v in extra.items() if k != "metadata"}
        return _RealEmbeddingClient(
            model=model,
            openai_api_base=_proxy_base_url(),
            openai_api_key=_virtual_key() or "unset",
            check_embedding_ctx_length=False,
            **embedding_extra,
        )
    return _EmbeddingClient(
        model=model,
        base_url=_proxy_base_url(),
        api_key=_virtual_key() or "unset",
        extra=extra,
    )


# --- ADR-023 Phase 4.2 shadow-fallback instrumentation: REVERTED at Phase 4.5 --
#
# `SHADOW_FALLBACK_ENABLED`/`shadow_alias_for`/`shadow_metadata`/
# `fire_shadow_chat_call` lived here from Phase 4 through Phase 4.5's cutover
# confirmation (Anthropic/Cohere keys revoked at the provider dashboards,
# 2026-06-28). They were explicitly speced in ADR-023/docs/MIGRATION_PLAN.md as
# temporary and feature-flagged-off-by-default, to be reverted once cutover
# was confirmed — not a permanent architectural addition, so removal here is
# the plan working as designed, not a loss of functionality. Full history
# (why it existed, the retroactive-validation reinterpretation, all 14 of its
# unit tests) is preserved in docs/PROJECT_MEMORY.md's ADR-023 entry and
# `memory/features/feature-15-local-fallback-migration.md`'s Phase 4 detail —
# consult those, not git blame, if this logic is ever needed again.
