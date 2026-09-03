"""Runtime Claude settings shared by the API and agent containers.

The API key is stored only as an encrypted value in Redis.  Reads return a
sanitised mapping so this module can be used by UI-facing code without ever
leaking the secret to the browser or to logs.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any

AI_RUNTIME_REDIS_KEY = "settings:ai_runtime"
AI_DAILY_CALL_KEY_PREFIX = "settings:ai_calls:day:"
AI_DAILY_COST_KEY_PREFIX = "settings:ai_cost_usd_micros:day:"

# Store currency as integer micro-dollars rather than Redis floating-point
# values.  This makes the atomic Lua comparison deterministic and avoids a
# rounding edge case allowing a request a few fractions of a cent above the
# configured budget.
_MICRODOLLARS_PER_USD = 1_000_000
_DAILY_COUNTER_TTL_SECONDS = 172_800

# The check and both reservations must live in one Redis operation: agents
# run in separate processes, so a Python read/check/write sequence would race
# under concurrent calls.  The script reserves the *maximum estimated* cost
# before the provider request.  A failed upstream request deliberately keeps
# its reservation: retry storms must never circumvent the owner budget.
_RESERVE_DAILY_ALLOWANCE_LUA = """
local calls = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost = tonumber(redis.call('GET', KEYS[2]) or '0')
local call_limit = tonumber(ARGV[1])
local budget_limit = tonumber(ARGV[2])
local reservation = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

if call_limit <= 0 or calls >= call_limit then
  return {0, 1, calls, cost}
end
if reservation <= 0 or budget_limit < reservation or cost > (budget_limit - reservation) then
  return {0, 2, calls, cost}
end

local updated_calls = redis.call('INCR', KEYS[1])
local updated_cost = redis.call('INCRBY', KEYS[2], reservation)
if updated_calls == 1 then
  redis.call('EXPIRE', KEYS[1], ttl)
end
if updated_cost == reservation then
  redis.call('EXPIRE', KEYS[2], ttl)
end
return {1, 0, updated_calls, updated_cost}
"""

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


@dataclass(frozen=True)
class DailyAIAllowance:
    """Outcome of an atomic daily Claude allowance reservation.

    ``reserved_usd`` is deliberately an upper-bound estimate, not a claim of
    Anthropic's final invoice.  It is the value used for the hard stop before
    any network request is sent.
    """

    allowed: bool
    reason: str | None
    calls_reserved: int
    reserved_usd: float


def _utc_day_key() -> str:
    return datetime.now(UTC).date().isoformat()


def _daily_keys() -> tuple[str, str]:
    day = _utc_day_key()
    return AI_DAILY_CALL_KEY_PREFIX + day, AI_DAILY_COST_KEY_PREFIX + day


def _as_int(raw: Any) -> int:
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _usd_to_microdollars(value: float | int, *, rounding: str) -> int:
    amount = Decimal(str(value)) * _MICRODOLLARS_PER_USD
    return max(0, int(amount.to_integral_value(rounding=rounding)))


def _microdollars_to_usd(value: int) -> float:
    return value / _MICRODOLLARS_PER_USD


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


def reserve_daily_ai_allowance(
    redis_client,
    *,
    call_limit: int,
    daily_budget_usd: float | int,
    reservation_usd: float | int,
) -> DailyAIAllowance:
    """Atomically reserve one call and its maximum estimated daily cost.

    This is intentionally fail-closed at the caller: Redis errors propagate so
    an AI provider can return its existing safe fallback rather than make an
    unaccounted provider request.  Day keys are UTC keys, therefore a new
    quota naturally starts at 00:00 UTC even though previous keys are kept for
    48 hours for short-lived diagnostics.
    """
    calls_key, cost_key = _daily_keys()
    budget_micros = _usd_to_microdollars(daily_budget_usd, rounding=ROUND_FLOOR)
    reservation_micros = _usd_to_microdollars(reservation_usd, rounding=ROUND_CEILING)
    result = redis_client.eval(
        _RESERVE_DAILY_ALLOWANCE_LUA,
        2,
        calls_key,
        cost_key,
        int(call_limit),
        budget_micros,
        reservation_micros,
        _DAILY_COUNTER_TTL_SECONDS,
    )
    if not isinstance(result, (list, tuple)) or len(result) < 4:
        raise RuntimeError("unexpected Redis daily AI allowance response")

    allowed, reason_code, calls_reserved, reserved_micros = (_as_int(item) for item in result[:4])
    reason = None
    if not allowed:
        reason = "daily_call_limit" if reason_code == 1 else "daily_budget"
    return DailyAIAllowance(
        allowed=bool(allowed),
        reason=reason,
        calls_reserved=calls_reserved,
        reserved_usd=_microdollars_to_usd(reserved_micros),
    )


def get_daily_ai_budget_status(redis_client, *, daily_budget_usd: float | int) -> dict[str, Any]:
    """Return read-only UTC daily reservation status for the Settings card.

    The response contains only accounting counters; it never contains an API
    key, provider prompt, or raw model response.
    """
    calls_key, cost_key = _daily_keys()
    budget_micros = _usd_to_microdollars(daily_budget_usd, rounding=ROUND_FLOOR)
    calls_reserved = _as_int(redis_client.get(calls_key))
    reserved_micros = _as_int(redis_client.get(cost_key))
    now = datetime.now(UTC)
    reset_at = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return {
        "daily_budget_reserved_usd": _microdollars_to_usd(reserved_micros),
        "daily_budget_remaining_usd": _microdollars_to_usd(max(0, budget_micros - reserved_micros)),
        "daily_calls_reserved": calls_reserved,
        "daily_budget_reset_at": reset_at,
    }


def consume_daily_call(redis_client, *, limit: int) -> bool:
    """Legacy call-only reservation kept for compatibility.

    New provider calls use :func:`reserve_daily_ai_allowance`, which reserves
    both this call slot and a USD upper bound in one Lua script.
    """
    if limit <= 0:
        return False
    key, _ = _daily_keys()
    count = int(redis_client.incr(key))
    if count == 1:
        redis_client.expire(key, _DAILY_COUNTER_TTL_SECONDS)
    return count <= limit
