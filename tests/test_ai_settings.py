
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.config import settings
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture()
def client(redis_client):
    day = datetime.now(UTC).date().isoformat()
    redis_client.delete("settings:ai_calls_enabled")
    redis_client.delete("settings:ai_runtime")
    redis_client.delete(f"settings:ai_calls:day:{day}")
    redis_client.delete(f"settings:ai_cost_usd_micros:day:{day}")
    with TestClient(app) as c:
        yield c
    redis_client.delete("settings:ai_calls_enabled")
    redis_client.delete("settings:ai_runtime")
    redis_client.delete(f"settings:ai_calls:day:{day}")
    redis_client.delete(f"settings:ai_cost_usd_micros:day:{day}")


@pytest.fixture()
def logged_in_client(client):
    response = client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": settings.demo_user_password},
    )
    assert response.status_code == 200
    return client


def test_requires_auth(client):
    assert client.get("/api/settings/ai").status_code == 401


def test_defaults_to_config_value_when_never_toggled(logged_in_client):
    response = logged_in_client.get("/api/settings/ai")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] == settings.ai_calls_enabled
    assert body["max_calls_per_minute"] == settings.ai_max_calls_per_minute
    assert body["high_stakes_model"] == settings.ai_model_high_stakes
    assert body["low_stakes_model"] == settings.ai_model_low_stakes
    assert body["max_calls_per_day"] == settings.ai_max_calls_per_day
    assert body["daily_budget_usd"] == min(
        settings.ai_daily_budget_usd, settings.ai_daily_budget_hard_cap_usd
    )
    assert body["daily_budget_hard_cap_usd"] == settings.ai_daily_budget_hard_cap_usd
    assert body["daily_budget_reserved_usd"] == 0
    assert body["daily_budget_remaining_usd"] == body["daily_budget_usd"]
    assert body["daily_calls_reserved"] == 0
    assert body["daily_budget_reset_at"].endswith("+00:00")
    assert body["api_key_configured"] is bool(settings.anthropic_api_key)


def test_runtime_controls_persist_without_exposing_api_key(logged_in_client):
    response = logged_in_client.put(
        "/api/settings/ai",
        json={
            "enabled": True,
            "low_stakes_model": "claude-haiku-4-5",
            "temperature": 0.35,
            "max_tokens": 512,
            "max_calls_per_day": 42,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["temperature"] == 0.35
    assert body["max_tokens"] == 512
    assert body["max_calls_per_day"] == 42
    assert "api_key" not in body


def test_daily_budget_above_deployment_hard_cap_is_rejected(logged_in_client):
    before = logged_in_client.get("/api/settings/ai").json()
    response = logged_in_client.put(
        "/api/settings/ai",
        json={
            "enabled": not before["enabled"],
            "daily_budget_usd": settings.ai_daily_budget_hard_cap_usd + 0.01,
        },
    )
    assert response.status_code == 422
    assert "hard cap" in response.json()["error"]["message"]
    assert logged_in_client.get("/api/settings/ai").json()["enabled"] is before["enabled"]


def test_toggle_off_then_on_persists_and_reflects_immediately(logged_in_client):
    off = logged_in_client.put("/api/settings/ai", json={"enabled": False})
    assert off.status_code == 200
    assert off.json()["enabled"] is False

    # Nouvelle requête GET — la valeur doit venir de Redis, pas d'un état
    # en mémoire du process (§D026 "effet immédiat, sans redéployer").
    read_back = logged_in_client.get("/api/settings/ai")
    assert read_back.json()["enabled"] is False

    on = logged_in_client.put("/api/settings/ai", json={"enabled": True})
    assert on.json()["enabled"] is True
    assert logged_in_client.get("/api/settings/ai").json()["enabled"] is True


def test_toggle_is_visible_directly_via_shared_helper(logged_in_client, redis_client):
    """Vérifie l'intégration réelle avec `shared.ai_governance` — le
    mécanisme que les agents (market_agent) consomment directement, pas
    seulement via l'API backend."""
    from shared.ai_governance import get_ai_calls_enabled

    logged_in_client.put("/api/settings/ai", json={"enabled": False})
    assert get_ai_calls_enabled(redis_client, default=True) is False

    logged_in_client.put("/api/settings/ai", json={"enabled": True})
    assert get_ai_calls_enabled(redis_client, default=False) is True
