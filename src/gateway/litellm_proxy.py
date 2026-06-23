"""
`MockLiteLLMProxy` — stdlib stand-in for the real LiteLLM proxy server (ADR-021
addendum, Feature 12/ADR-018).

This sandbox has no Docker network egress (ADR-007/ADR-021), so the `litellm`
service `docker-compose.yml` already provisions (mounting
`infra/litellm_config.yaml` as `/app/config.yaml`) cannot actually be run here.
This class models the specific proxy *behaviors* ADR-018 configures — fallback
routing, semantic caching with the eval-determinism carve-out, per-virtual-key
rate limiting, and trace_id-tagged request logging — directly against that same
YAML file, so the config file itself stays the single source of truth rather
than being duplicated into Python literals.

Deliberately out of scope (unlike the config behaviors above): real model
invocation. `client_factory._ChatClient.invoke()` is still a NotImplementedError
stub pending Open Question #15 (no `langchain_openai`/provider SDK access in
this sandbox) — this class's `complete()` takes a `provider_call` callable so
tests can simulate primary/fallback success or failure without a real network
call, the same boundary-mocking pattern `execute_tool`'s `get_staging_api_client`
factory already established (ADR-016/Feature 10).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "infra" / "litellm_config.yaml"


class LiteLLMProxyError(RuntimeError):
    """Base class for this module's errors."""


class UnknownModelAliasError(LiteLLMProxyError):
    """Raised when `complete()` is called with an alias absent from
    `infra/litellm_config.yaml`'s `model_list` — never silently routed
    anywhere (same "never silently default" discipline as every node's
    error class)."""


class UnknownVirtualKeyError(LiteLLMProxyError):
    """Raised when a virtual key not declared under `general_settings.virtual_keys`
    is used — a real proxy would reject the request the same way."""


class RateLimitExceededError(LiteLLMProxyError):
    """Raised when a virtual key's `rpm_limit` (per this mock's call-count proxy
    for "requests per minute" — no real wall-clock window in a deterministic
    unit test) is exceeded."""


class AllProvidersFailedError(LiteLLMProxyError):
    """Raised when the primary and every configured fallback in an alias's
    chain all raised — mirrors a real proxy giving up and surfacing an error
    rather than silently returning a partial/garbage response."""


class _AliasConfig:
    __slots__ = ("alias", "provider_model", "fallback_aliases")

    def __init__(self, alias: str, provider_model: str, fallback_aliases: List[str]):
        self.alias = alias
        self.provider_model = provider_model
        self.fallback_aliases = fallback_aliases


class _VirtualKeyConfig:
    __slots__ = ("key_alias", "rpm_limit", "max_budget", "budget_duration")

    def __init__(self, key_alias: str, rpm_limit: int, max_budget: float, budget_duration: str):
        self.key_alias = key_alias
        self.rpm_limit = rpm_limit
        self.max_budget = max_budget
        self.budget_duration = budget_duration


class MockLiteLLMProxy:
    """One instance models one running proxy: its own cache and per-key
    request counters. Tests construct a fresh instance per test (mirrors how
    a real `make eval`/app run would talk to one long-lived proxy process,
    but unit tests don't want state leaking across cases)."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        raw = yaml.safe_load(Path(config_path).read_text())

        self._aliases: Dict[str, _AliasConfig] = {}
        for entry in raw.get("model_list", []):
            alias = entry["model_name"]
            params = entry["litellm_params"]
            self._aliases[alias] = _AliasConfig(
                alias=alias,
                provider_model=params["model"],
                fallback_aliases=list(params.get("fallbacks") or []),
            )

        self._virtual_keys: Dict[str, _VirtualKeyConfig] = {}
        for entry in raw.get("general_settings", {}).get("virtual_keys", []):
            self._virtual_keys[entry["key_alias"]] = _VirtualKeyConfig(
                key_alias=entry["key_alias"],
                rpm_limit=entry["rpm_limit"],
                max_budget=entry["max_budget"],
                budget_duration=entry["budget_duration"],
            )

        self.cache_enabled: bool = bool(raw.get("litellm_settings", {}).get("cache"))

        self._cache: Dict[tuple, Any] = {}
        self._request_counts: Dict[str, int] = defaultdict(int)
        #: append-only log of every `complete()` call's observable facts —
        #: the test-facing equivalent of the real proxy's cost/usage log
        #: (ADR-018's trace_id-joinability requirement).
        self.call_log: List[Dict[str, Any]] = []

    def known_aliases(self) -> List[str]:
        return sorted(self._aliases)

    def fallback_chain(self, alias: str) -> List[str]:
        """Returns `[alias, *its configured fallback aliases]`, in routing
        order. Raises `UnknownModelAliasError` rather than returning an empty
        chain for a typo'd alias."""
        if alias not in self._aliases:
            raise UnknownModelAliasError(
                f"{alias!r} is not declared in infra/litellm_config.yaml's model_list"
            )
        return [alias, *self._aliases[alias].fallback_aliases]

    def complete(
        self,
        alias: str,
        prompt: str,
        *,
        virtual_key: Optional[str] = None,
        cache: Optional[dict] = None,
        metadata: Optional[dict] = None,
        provider_call: Callable[[str, str], Any],
    ) -> Any:
        """Routes one chat-completion request through fallback + cache +
        rate-limit logic.

        `provider_call(alias, prompt)` is the boundary mock standing in for
        the real network hop to whichever provider model an alias resolves
        to; raise from it to simulate a timeout/error and exercise fallback.
        """
        chain = self.fallback_chain(alias)
        self._check_rate_limit(virtual_key)

        no_cache = bool(cache and cache.get("no-cache"))
        cache_key = (alias, prompt) if (self.cache_enabled and not no_cache) else None
        if cache_key is not None and cache_key in self._cache:
            self._record_call(alias, virtual_key, metadata, served_by=alias, cache_hit=True)
            return self._cache[cache_key]

        result = None
        served_by = None
        last_exc: Optional[Exception] = None
        for candidate in chain:
            try:
                result = provider_call(candidate, prompt)
                served_by = candidate
                break
            except Exception as exc:  # noqa: BLE001 - intentionally broad, mirrors "any provider failure"
                last_exc = exc
                continue
        if served_by is None:
            raise AllProvidersFailedError(
                f"every alias in the fallback chain {chain} for {alias!r} failed"
            ) from last_exc

        if cache_key is not None:
            self._cache[cache_key] = result
        self._record_call(alias, virtual_key, metadata, served_by=served_by, cache_hit=False)
        return result

    def _check_rate_limit(self, virtual_key: Optional[str]) -> None:
        # Mirrors client_factory._virtual_key(): no key configured yet is
        # local/dev usage, not an error (ADR-018's decision explicitly allows
        # this before keys are provisioned).
        if virtual_key is None:
            return
        if virtual_key not in self._virtual_keys:
            raise UnknownVirtualKeyError(
                f"{virtual_key!r} is not declared under general_settings.virtual_keys"
            )
        self._request_counts[virtual_key] += 1
        limit = self._virtual_keys[virtual_key].rpm_limit
        if self._request_counts[virtual_key] > limit:
            raise RateLimitExceededError(
                f"virtual key {virtual_key!r} exceeded its rpm_limit ({limit})"
            )

    def _record_call(
        self,
        alias: str,
        virtual_key: Optional[str],
        metadata: Optional[dict],
        *,
        served_by: str,
        cache_hit: bool,
    ) -> None:
        self.call_log.append(
            {
                "alias": alias,
                "virtual_key": virtual_key,
                "metadata": metadata or {},
                "served_by": served_by,
                "cache_hit": cache_hit,
            }
        )
