"""Route de l'interrupteur IA global — §B10 "Interrupteur IA dédié dans
Settings" (D026, R15). Le contrat existe avant l'écran dédié (pas encore
construit, arrivera avec un futur écran Settings) — même principe que les
contrats publiés en avance ailleurs dans le projet (B04, B06, B07)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..config import settings
from ..encryption import EncryptionKeyMissing, encrypt_secret
from ..models import User
from ..redis_client import redis_client
from ..schemas.ai_settings import AISettingsOut, UpdateAISettingsRequest
from shared.ai_runtime_settings import (
    api_key_is_configured,
    get_ai_runtime_settings,
    set_ai_runtime_settings,
    set_encrypted_api_key,
)

router = APIRouter(prefix="/api/settings/ai", tags=["settings"])


def _current() -> AISettingsOut:
    from shared.ai_governance import get_ai_calls_enabled

    runtime = get_ai_runtime_settings(
        redis_client,
        defaults={
            "max_calls_per_minute": settings.ai_max_calls_per_minute,
            "max_calls_per_day": settings.ai_max_calls_per_day,
            "high_stakes_model": settings.ai_model_high_stakes,
            "low_stakes_model": settings.ai_model_low_stakes,
            "temperature": settings.ai_temperature,
            "max_tokens": settings.ai_max_tokens,
            "timeout_seconds": settings.ai_timeout_seconds,
            "daily_budget_usd": settings.ai_daily_budget_usd,
        },
    )
    return AISettingsOut(
        enabled=get_ai_calls_enabled(redis_client, default=settings.ai_calls_enabled),
        max_calls_per_minute=int(runtime["max_calls_per_minute"]),
        max_calls_per_day=int(runtime["max_calls_per_day"]),
        high_stakes_model=str(runtime["high_stakes_model"]),
        low_stakes_model=str(runtime["low_stakes_model"]),
        temperature=float(runtime["temperature"]),
        max_tokens=int(runtime["max_tokens"]),
        timeout_seconds=float(runtime["timeout_seconds"]),
        daily_budget_usd=float(runtime["daily_budget_usd"]),
        api_key_configured=api_key_is_configured(
            redis_client, fallback=settings.anthropic_api_key, encryption_key=settings.app_encryption_key
        ),
    )


@router.get("", response_model=AISettingsOut)
def get_ai_settings(user: User = Depends(get_current_user)) -> AISettingsOut:
    return _current()


@router.put("", response_model=AISettingsOut)
def update_ai_settings(
    payload: UpdateAISettingsRequest, user: User = Depends(get_current_user)
) -> AISettingsOut:
    from shared.ai_governance import set_ai_calls_enabled

    # §D026 "en un clic sans redéployer" : effet immédiat — le prochain
    # tick de n'importe quel agent consommateur d'IA relit ce flag avant
    # son prochain appel (voir agents/market_agent/main.py).
    set_ai_calls_enabled(redis_client, payload.enabled)
    values = payload.model_dump(exclude_none=True)
    values.pop("enabled", None)
    api_key = values.pop("api_key", None)
    if values:
        set_ai_runtime_settings(
            redis_client,
            values,
            defaults={
                "max_calls_per_minute": settings.ai_max_calls_per_minute,
                "max_calls_per_day": settings.ai_max_calls_per_day,
                "high_stakes_model": settings.ai_model_high_stakes,
                "low_stakes_model": settings.ai_model_low_stakes,
                "temperature": settings.ai_temperature,
                "max_tokens": settings.ai_max_tokens,
                "timeout_seconds": settings.ai_timeout_seconds,
                "daily_budget_usd": settings.ai_daily_budget_usd,
            },
        )
    if api_key is not None:
        if api_key == "":
            # Empty input intentionally clears the persisted key; agents then
            # fall back to ANTHROPIC_API_KEY from the deployment environment.
            import json

            runtime = get_ai_runtime_settings(redis_client)
            runtime.pop("api_key_ciphertext", None)
            redis_client.set("settings:ai_runtime", json.dumps(runtime, sort_keys=True))
        else:
            try:
                set_encrypted_api_key(redis_client, encrypt_secret(api_key))
            except EncryptionKeyMissing as exc:
                raise HTTPException(status_code=503, detail="AI key encryption is not configured") from exc
    return _current()
