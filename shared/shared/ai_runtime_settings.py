"""Runtime Claude settings shared by the API and agent containers.

The API key is stored only as an encrypted value in Redis.  Reads return a
sanitised mapping so this module can be used by UI-facing code without ever
leaking the secret to the browser or to logs.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

AI_RUNTIME_REDIS_KEY = "settings:ai_runtime"
AI_DAILY_CALL_KEY_PREFIX = "settings:ai_calls:day:"

DEFAULTS: dict[str, Any] = {
    "max_calls_per_minute": 30,
    "max_calls_per_day": 50,
    "high_stakes_model": "claude-sonnet-4-5",
    "low_stakes_model": "claude-haiku-4-5",
    "temperature": 0.2,
    "max_tokens": 1024,
    "timeout_seconds": 20.0,
    "daily_budget_usd": 2.0,
}


def _normalise_daily_budget_hard_cap(value: float | int | None) -> float:
    """Return a safe server-side USD ceiling for UI-controlled budgets."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < float(value) <= 10_000:
        return float(value)
    return 10.0


def get_ai_runtime_settings(
    redis_client,
    *,
    defaults: dict[str, Any] | None = None,
    daily_budget_hard_cap_usd: float | int | None = None,
) -> dict[str, Any]:
    """Return validated, non-secret runtime settings merged with defaults.

    ``daily_budget_hard_cap_usd`` belongs to the deployment configuration,
    never to the Redis/UI payload.  Existing Redis values are clamped during
    reads as an additional defence if an older deployment stored a larger
    budget before this invariant was introduced.
    """
    hard_cap = _normalise_daily_budget_hard_cap(daily_budget_hard_cap_usd)
    merged = {**DEFAULTS, **(defaults or {})}
    merged["daily_budget_usd"] = min(float(merged["daily_budget_usd"]), hard_cap)
    raw = redis_client.get(AI_RUNTIME_REDIS_KEY)
    if raw is None:
        return merged
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        return merged
    if not isinstance(stored, dict):
        return merged
    for key in DEFAULTS:
        value = stored.get(key)
        if key not in stored:
            continue
        if key in {"max_calls_per_minute", "max_calls_per_day", "max_tokens"}:
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                merged[key] = value
        elif key in {"temperature"}:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= float(value) <= 1:
                merged[key] = float(value)
        elif key in {"timeout_seconds"}:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 1 <= float(value) <= 120:
                merged[key] = float(value)
        elif key in {"daily_budget_usd"}:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= float(value) <= 10_000:
                merged[key] = min(float(value), hard_cap)
        elif isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    return merged


def set_ai_runtime_settings(
    redis_client,
    values: dict[str, Any],
    *,
    defaults: dict[str, Any] | None = None,
    daily_budget_hard_cap_usd: float | int | None = None,
) -> None:
    """Persist non-secret settings without allowing a UI budget above the cap."""
    hard_cap = _normalise_daily_budget_hard_cap(daily_budget_hard_cap_usd)
    current = get_ai_runtime_settings(
        redis_client,
        defaults=defaults,
        daily_budget_hard_cap_usd=hard_cap,
    )
    for key in DEFAULTS:
        if key in values:
            current[key] = min(float(values[key]), hard_cap) if key == "daily_budget_usd" else values[key]
    redis_client.set(AI_RUNTIME_REDIS_KEY, json.dumps(current, sort_keys=True))


def get_configured_api_key(redis_client, *, fallback: str = "", encryption_key: str | None = None) -> str:
    """Resolve the encrypted key for an agent, falling back to its env key.

    A missing encryption key or malformed ciphertext never prevents an agent
    from starting; it simply uses the deployment-provided environment key.
    """
    raw = redis_client.get(AI_RUNTIME_REDIS_KEY)
    if raw is None:
        return fallback
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        stored = json.loads(raw)
        ciphertext = stored.get("api_key_ciphertext") if isinstance(stored, dict) else None
        key = encryption_key if encryption_key is not None else os.environ.get("APP_ENCRYPTION_KEY", "")
        if not ciphertext or not key:
            return fallback
        from shared.encryption import decrypt_secret

        return decrypt_secret(ciphertext, key=key)
    except Exception:  # noqa: BLE001 - env fallback is the safe compatibility path
        return fallback


def set_encrypted_api_key(
    redis_client,
    ciphertext: str,
    *,
    daily_budget_hard_cap_usd: float | int | None = None,
) -> None:
    """Store an already-encrypted API key alongside runtime settings."""
    current = get_ai_runtime_settings(
        redis_client,
        daily_budget_hard_cap_usd=daily_budget_hard_cap_usd,
    )
    current["api_key_ciphertext"] = ciphertext
    redis_client.set(AI_RUNTIME_REDIS_KEY, json.dumps(current, sort_keys=True))


def api_key_is_configured(redis_client, *, fallback: str = "", encryption_key: str | None = None) -> bool:
    return bool(get_configured_api_key(redis_client, fallback=fallback, encryption_key=encryption_key))


def consume_daily_call(redis_client, *, limit: int) -> bool:
    """Atomically reserve one daily call slot across all agent processes."""
    if limit <= 0:
        return False
    key = AI_DAILY_CALL_KEY_PREFIX + datetime.now(UTC).date().isoformat()
    count = int(redis_client.incr(key))
    if count == 1:
        redis_client.expire(key, 172_800)
    return count <= limit
