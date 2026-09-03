"""Focused verification for the server-side daily Claude USD reservation."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.ai_runtime_settings import (
    AI_DAILY_CALL_KEY_PREFIX,
    AI_DAILY_COST_KEY_PREFIX,
    get_daily_ai_budget_status,
    reserve_daily_ai_allowance,
)


def _clear_today(redis_client) -> None:
    day = datetime.now(UTC).date().isoformat()
    redis_client.delete(AI_DAILY_CALL_KEY_PREFIX + day, AI_DAILY_COST_KEY_PREFIX + day)


def test_daily_usd_reservation_blocks_before_incrementing_a_second_call(redis_client):
    """The Lua reservation keeps both counters unchanged on a budget reject."""
    _clear_today(redis_client)
    try:
        first = reserve_daily_ai_allowance(
            redis_client,
            call_limit=3,
            daily_budget_usd=0.01,
            reservation_usd=0.006,
        )
        blocked = reserve_daily_ai_allowance(
            redis_client,
            call_limit=3,
            daily_budget_usd=0.01,
            reservation_usd=0.006,
        )
        status = get_daily_ai_budget_status(redis_client, daily_budget_usd=0.01)

        assert first.allowed is True
        assert first.calls_reserved == 1
        assert blocked.allowed is False
        assert blocked.reason == "daily_budget"
        assert blocked.calls_reserved == 1
        assert status["daily_calls_reserved"] == 1
        assert status["daily_budget_reserved_usd"] == 0.006
        assert status["daily_budget_remaining_usd"] == 0.004
    finally:
        _clear_today(redis_client)


def test_daily_call_limit_and_usd_limit_share_one_allowance_reservation(redis_client):
    """A rejected call quota must not charge an additional estimated cost."""
    _clear_today(redis_client)
    try:
        first = reserve_daily_ai_allowance(
            redis_client,
            call_limit=1,
            daily_budget_usd=1,
            reservation_usd=0.1,
        )
        blocked = reserve_daily_ai_allowance(
            redis_client,
            call_limit=1,
            daily_budget_usd=1,
            reservation_usd=0.1,
        )
        status = get_daily_ai_budget_status(redis_client, daily_budget_usd=1)

        assert first.allowed is True
        assert blocked.allowed is False
        assert blocked.reason == "daily_call_limit"
        assert status["daily_calls_reserved"] == 1
        assert status["daily_budget_reserved_usd"] == 0.1
    finally:
        _clear_today(redis_client)
