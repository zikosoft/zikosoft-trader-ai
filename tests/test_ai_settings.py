
from __future__ import annotations

import pytest
from app.config import settings
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture()
def client(redis_client):
    redis_client.delete("settings:ai_calls_enabled")
    with TestClient(app) as c:
        yield c
    redis_client.delete("settings:ai_calls_enabled")


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
