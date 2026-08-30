"""B05 — authentification locale. Tests d'intégration contre l'app FastAPI
réelle (TestClient), PostgreSQL et Redis réels — cohérent avec le reste du
socle (pas de mock, on prouve que ça marche pour de vrai)."""

from __future__ import annotations

import pytest
from app.config import settings
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture(autouse=True)
def _clean_auth_state(redis_client):
    """Le login/logout commitent leur propre transaction (indépendante du
    rollback de `db_session`) — sans ce nettoyage, une session ou un
    compteur de rate limit créé par un test fuiterait vers le suivant."""
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM user_sessions"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM user_sessions"))
        conn.commit()
    redis_client.flushdb()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_login_success_sets_cookie_and_returns_user(client):
    response = client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": settings.demo_user_password},
    )
    assert response.status_code == 200
    assert response.json()["user"]["email"] == settings.demo_user_email
    assert settings.session_cookie_name in response.cookies


def test_login_wrong_password_returns_generic_error(client):
    response = client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": "definitely-wrong"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_login_unknown_email_returns_identical_message_to_wrong_password(client):
    """Critère d'acceptation B05 : "message d'erreur sans fuite d'information"
    — un attaquant ne doit pas pouvoir distinguer "email inconnu" de "mot de
    passe incorrect" à partir du message renvoyé."""
    wrong_password = client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": "definitely-wrong"},
    ).json()["error"]["message"]
    unknown_email = client.post(
        "/api/auth/login",
        json={"email": "nobody-registered@example.com", "password": "whatever"},
    ).json()["error"]["message"]
    assert wrong_password == unknown_email


def test_me_requires_valid_session(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_me_works_with_valid_session(client):
    client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": settings.demo_user_password},
    )
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == settings.demo_user_email


def test_logout_revokes_session(client):
    client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": settings.demo_user_password},
    )
    assert client.get("/api/auth/me").status_code == 200

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    assert client.get("/api/auth/me").status_code == 401


def test_logout_is_idempotent_without_session(client):
    """Un logout sans cookie (ou avec un cookie déjà révoqué) ne doit jamais
    lever d'erreur — voir docstring de `revoke_session`."""
    response = client.post("/api/auth/logout")
    assert response.status_code == 200


def test_password_never_appears_in_technical_error_logs(client):
    """Un login échoué écrit une ligne dans technical_error_logs (B36) — elle
    ne doit jamais contenir le mot de passe soumis."""
    secret_password = "s3cr3t-should-never-leak"  # noqa: S105 — valeur de test
    client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": secret_password},
    )
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT request_payload, response_or_error FROM technical_error_logs "
                "WHERE module = 'AUTH' AND feature = 'login' ORDER BY occurred_at DESC LIMIT 1"
            )
        ).fetchall()
    assert rows, "expected a technical_error_logs row for the failed login"
    for row in rows:
        for value in row:
            assert secret_password not in str(value)


def test_rate_limit_blocks_after_max_attempts(client):
    for _ in range(settings.login_rate_limit_max_attempts):
        response = client.post(
            "/api/auth/login",
            json={"email": settings.demo_user_email, "password": "wrong"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/api/auth/login",
        json={"email": settings.demo_user_email, "password": "wrong"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"


def test_demo_credentials_endpoint_reflects_config(client):
    response = client.get("/api/auth/demo-credentials")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == settings.demo_user_email
    assert body["password"] == settings.demo_user_password
