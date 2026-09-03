"""Shared, server-side construction of the Claude runtime configuration.

The browser can edit only the non-secret runtime settings stored in Redis.
This module combines those values with deployment-owned defaults and the
``.env`` hard budget cap.  It is deliberately API-only: it does not expose a
provider, API key, prompt, or response to an HTTP client.
"""

from __future__ import annotations

from shared.ai_governance import get_ai_calls_enabled
from shared.ai_provider import AIProvider, AIProviderConfig, claude_cost_controls_from_env, get_ai_provider
from shared.ai_runtime_settings import get_ai_runtime_settings, get_configured_api_key

from .config import settings


def runtime_defaults() -> dict[str, object]:
    """Bootstrap values used until Settings has persisted a runtime value."""
    return {
        "max_calls_per_minute": settings.ai_max_calls_per_minute,
        "max_calls_per_day": settings.ai_max_calls_per_day,
        "high_stakes_model": settings.ai_model_high_stakes,
        "low_stakes_model": settings.ai_model_low_stakes,
        "temperature": settings.ai_temperature,
        "max_tokens": settings.ai_max_tokens,
        "timeout_seconds": settings.ai_timeout_seconds,
        "daily_budget_usd": settings.ai_daily_budget_usd,
    }


def get_readonly_ai_provider(redis_client, *, max_tokens: int) -> AIProvider | None:
    """Return the bounded provider used by read-only UI explainers.

    A missing key, disabled AI, malformed Redis state, or unavailable Redis
    returns ``None``.  Callers must use a deterministic local fallback rather
    than attempting an unmetered provider request.  ``max_tokens`` is an
    endpoint-owned ceiling, so a Settings value can lower it but never raise
    the cost of this low-stakes feature.
    """
    try:
        runtime = get_ai_runtime_settings(
            redis_client,
            defaults=runtime_defaults(),
            daily_budget_hard_cap_usd=settings.ai_daily_budget_hard_cap_usd,
        )
        api_key = get_configured_api_key(
            redis_client,
            fallback=settings.anthropic_api_key,
            encryption_key=settings.app_encryption_key,
        )
        if not api_key:
            return None
        return get_ai_provider(
            api_key=api_key,
            config=AIProviderConfig(
                enabled=get_ai_calls_enabled(redis_client, default=settings.ai_calls_enabled),
                max_calls_per_minute=int(runtime["max_calls_per_minute"]),
                max_calls_per_day=int(runtime["max_calls_per_day"]),
                daily_quota_client=redis_client,
                daily_budget_usd=float(runtime["daily_budget_usd"]),
                high_stakes_model=str(runtime["high_stakes_model"]),
                # Ask Ziko is deliberately fixed to the cheapest supported
                # tier. Settings still controls quotas and budget, but cannot
                # upgrade this optional read-only feature to Sonnet.
                low_stakes_model="claude-haiku-4-5",
                timeout_seconds=float(runtime["timeout_seconds"]),
                temperature=float(runtime["temperature"]),
                max_tokens=min(max_tokens, int(runtime["max_tokens"])),
                **claude_cost_controls_from_env(),
            ),
        )
    except Exception:  # noqa: BLE001 - callers safely fall back without an AI request
        return None
