
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.config import settings
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()


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


@pytest.fixture()
def paper_client(logged_in_client):
    response = logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    assert response.status_code == 200
    return logged_in_client


@pytest.fixture()
def demo_user_id() -> uuid.UUID:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": settings.demo_user_email}
        ).scalar_one()


@pytest.fixture()
def paper_context_id(demo_user_id) -> uuid.UUID:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'PAPER'"),
            {"uid": demo_user_id},
        ).scalar_one()


@pytest.fixture()
def replay_context_id(demo_user_id) -> uuid.UUID:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
            {"uid": demo_user_id},
        ).scalar_one()


def _insert_alert(
    *,
    user_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    category: str = "system_health",
    severity: str = "WARNING",
    title: str = "Test alert",
    message: str = "Message de test",
    is_read: bool = False,
    dedup_key: str | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    alert_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts "
                "(id, user_id, execution_context_id, category, severity, title, message, "
                " related_entity_type, related_entity_id, is_read, dedup_key, metadata_json, created_at, updated_at) "
                "VALUES (:id, :user_id, :ctx_id, :category, :severity, :title, :message, "
                " NULL, NULL, :is_read, :dedup_key, '{}'::jsonb, :created_at, :created_at)"
            ),
            {
                "id": alert_id,
                "user_id": user_id,
                "ctx_id": execution_context_id,
                "category": category,
                "severity": severity,
                "title": title,
                "message": message,
                "is_read": is_read,
                "dedup_key": dedup_key or uuid.uuid4().hex,
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return alert_id


class TestListAlerts:
    def test_requires_auth(self, client):
        assert client.get("/api/alerts").status_code == 401

    def test_no_active_context_is_a_clear_validation_error(self, logged_in_client):
        response = logged_in_client.get("/api/alerts")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_lists_alerts_for_active_context_only(self, paper_client, demo_user_id, paper_context_id, replay_context_id):
        _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, title="Paper alert")
        _insert_alert(user_id=demo_user_id, execution_context_id=replay_context_id, title="Replay alert")

        response = paper_client.get("/api/alerts")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["alerts"][0]["title"] == "Paper alert"

    def test_most_recent_first(self, paper_client, demo_user_id, paper_context_id):
        old = _insert_alert(
            user_id=demo_user_id, execution_context_id=paper_context_id, title="Ancienne",
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        recent = _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, title="Récente")

        response = paper_client.get("/api/alerts")
        ids = [a["id"] for a in response.json()["alerts"]]
        assert ids == [str(recent), str(old)]

    def test_unread_only_filter(self, paper_client, demo_user_id, paper_context_id):
        _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, title="Lue", is_read=True)
        _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, title="Non lue", is_read=False)

        response = paper_client.get("/api/alerts", params={"unread_only": "true"})
        titles = [a["title"] for a in response.json()["alerts"]]
        assert titles == ["Non lue"]

    def test_pagination_limit(self, paper_client, demo_user_id, paper_context_id):
        for i in range(5):
            _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, title=f"Alerte {i}")

        response = paper_client.get("/api/alerts", params={"limit": 2})
        body = response.json()
        assert body["total"] == 5
        assert len(body["alerts"]) == 2


class TestUnreadCount:
    def test_requires_auth(self, client):
        assert client.get("/api/alerts/unread-count").status_code == 401

    def test_counts_only_active_context_unread(self, paper_client, demo_user_id, paper_context_id, replay_context_id):
        _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, is_read=False)
        _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, is_read=True)
        _insert_alert(user_id=demo_user_id, execution_context_id=replay_context_id, is_read=False)

        response = paper_client.get("/api/alerts/unread-count")
        assert response.json()["unread_count"] == 1


class TestMarkRead:
    def test_marks_single_alert_read(self, paper_client, demo_user_id, paper_context_id):
        alert_id = _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, is_read=False)

        response = paper_client.post(f"/api/alerts/{alert_id}/read")
        assert response.status_code == 200
        assert response.json()["updated_count"] == 1

        with engine.connect() as conn:
            is_read = conn.execute(text("SELECT is_read FROM alerts WHERE id = :id"), {"id": alert_id}).scalar_one()
        assert is_read is True

    def test_marking_already_read_alert_is_a_noop(self, paper_client, demo_user_id, paper_context_id):
        alert_id = _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, is_read=True)
        response = paper_client.post(f"/api/alerts/{alert_id}/read")
        assert response.json()["updated_count"] == 0

    def test_marking_unknown_alert_is_a_noop_not_an_error(self, paper_client):
        response = paper_client.post(f"/api/alerts/{uuid.uuid4()}/read")
        assert response.status_code == 200
        assert response.json()["updated_count"] == 0

    def test_mark_all_read_scoped_to_active_context(
        self, paper_client, demo_user_id, paper_context_id, replay_context_id
    ):
        _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, is_read=False)
        _insert_alert(user_id=demo_user_id, execution_context_id=paper_context_id, is_read=False)
        replay_alert = _insert_alert(user_id=demo_user_id, execution_context_id=replay_context_id, is_read=False)

        response = paper_client.post("/api/alerts/read-all")
        assert response.status_code == 200
        assert response.json()["updated_count"] == 2

        with engine.connect() as conn:
            replay_is_read = conn.execute(
                text("SELECT is_read FROM alerts WHERE id = :id"), {"id": replay_alert}
            ).scalar_one()
        assert replay_is_read is False  # §jamais acquitté depuis un autre contexte
