"""B30 — Profil d'expérience utilisateur (`GET`/`PUT /api/settings/profile`).
Contre PostgreSQL/Redis réels et l'app FastAPI réelle (TestClient), aucun
mock. Vérifie : défaut `novice`, auth requise, mise à jour vers chacun des
trois paliers, persistance entre requêtes, et rejet Pydantic (422) d'une
valeur de profil invalide — cohérent avec les conventions de
`tests/test_strategy_instances_api.py` (chaîne de fixtures
`client`/`logged_in_client`, nettoyage Postgres + Redis)."""

from __future__ import annotations

import pytest
from app.config import settings
from app.db import engine
from app.main import app
from app.profile_limits import PROFILE_LIMITS
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("UPDATE users SET experience_profile = 'novice' WHERE email = :email"), {"email": settings.demo_user_email})
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("UPDATE users SET experience_profile = 'novice' WHERE email = :email"), {"email": settings.demo_user_email})
        conn.commit()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def logged_in_client(client):
    response = client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": settings.demo_user_password},
    )
    assert response.status_code == 200
    return client


class TestGetProfile:
    def test_requires_auth(self, client):
        response = client.get("/api/settings/profile")
        assert response.status_code == 401

    def test_defaults_to_novice(self, logged_in_client):
        response = logged_in_client.get("/api/settings/profile")
        assert response.status_code == 200
        body = response.json()
        assert body["profile"] == "novice"
        assert body["limits"] == {
            "max_active_strategies": PROFILE_LIMITS["novice"]["max_active_strategies"],
            "max_symbols": PROFILE_LIMITS["novice"]["max_symbols"],
            "order_risk_pct": PROFILE_LIMITS["novice"]["order_risk_pct"],
            "daily_loss_pct": PROFILE_LIMITS["novice"]["daily_loss_pct"],
            "approval_mode": PROFILE_LIMITS["novice"]["approval_mode"],
        }


class TestUpdateProfile:
    def test_requires_auth(self, client):
        response = client.put("/api/settings/profile", json={"profile": "expert"})
        assert response.status_code == 401

    @pytest.mark.parametrize("profile", ["novice", "intermediate", "expert"])
    def test_update_to_each_tier_returns_matching_limits(self, logged_in_client, profile):
        response = logged_in_client.put("/api/settings/profile", json={"profile": profile})
        assert response.status_code == 200
        body = response.json()
        assert body["profile"] == profile
        expected = PROFILE_LIMITS[profile]
        assert body["limits"]["max_active_strategies"] == expected["max_active_strategies"]
        assert body["limits"]["max_symbols"] == expected["max_symbols"]
        assert body["limits"]["order_risk_pct"] == expected["order_risk_pct"]
        assert body["limits"]["daily_loss_pct"] == expected["daily_loss_pct"]
        assert body["limits"]["approval_mode"] == expected["approval_mode"]

    def test_update_persists_across_requests(self, logged_in_client):
        put_response = logged_in_client.put("/api/settings/profile", json={"profile": "intermediate"})
        assert put_response.status_code == 200

        get_response = logged_in_client.get("/api/settings/profile")
        assert get_response.status_code == 200
        assert get_response.json()["profile"] == "intermediate"

    def test_invalid_profile_value_rejected_with_422(self, logged_in_client):
        response = logged_in_client.put("/api/settings/profile", json={"profile": "does-not-exist"})
        assert response.status_code == 422

    def test_missing_profile_field_rejected_with_422(self, logged_in_client):
        response = logged_in_client.put("/api/settings/profile", json={})
        assert response.status_code == 422
