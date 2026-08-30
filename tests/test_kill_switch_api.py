"""B31 — Kill switch trading (`/api/system/kill-switch/*`, `backend/app/
kill_switch.py`). Contre PostgreSQL/Redis réels et l'app FastAPI réelle
(TestClient), aucun mock — utilise la vraie stratégie
`moving_average_crossover` synchronisée au démarrage par le registre B11
(même précédent que `test_strategy_instances_api.py`)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from app.config import settings
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

VALID_PARAMS = {
    "timeframe": "1Day",
    "short_period": 10,
    "long_period": 30,
    "stop_loss_pct": 2.0,
    "take_profit_pct": 4.0,
}


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM audit_events WHERE action LIKE 'KILL_SWITCH_%'"))
        conn.execute(text("DELETE FROM alerts WHERE category = 'kill_switch'"))
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM audit_events WHERE action LIKE 'KILL_SWITCH_%'"))
        conn.execute(text("DELETE FROM alerts WHERE category = 'kill_switch'"))
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()


@pytest.fixture()
def client():
    with TestClient(app) as c:  # déclenche le lifespan -> sync réelle de strategies/
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


def _create_active_instance(client, **overrides) -> dict:
    payload = {
        "type_code": "moving_average_crossover",
        "name": "Kill switch test",
        "symbols": ["AAPL"],
        "parameters": VALID_PARAMS,
    }
    payload.update(overrides)
    response = client.post("/api/strategies/instances", json=payload)
    assert response.status_code == 201, response.text
    instance = response.json()
    response = client.post(f"/api/strategies/instances/{instance['id']}/activate")
    assert response.status_code == 200, response.text
    return response.json()


def _strategy_status(strategy_id) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT status FROM strategies WHERE id = :id"), {"id": strategy_id}).scalar_one()


def _audit_events(action: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM audit_events WHERE action = :action ORDER BY created_at"), {"action": action}
        ).mappings().all()
    return [dict(r) for r in rows]


def _kill_switch_alerts() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT a.*, ec.kind FROM alerts a "
                "JOIN execution_contexts ec ON ec.id = a.execution_context_id "
                "WHERE a.category = 'kill_switch' ORDER BY ec.kind"
            )
        ).mappings().all()
    return [dict(r) for r in rows]


class TestKillSwitchStatus:
    def test_requires_auth(self, client):
        response = client.get("/api/system/kill-switch/status")
        assert response.status_code == 401

    def test_defaults_to_not_engaged(self, logged_in_client):
        response = logged_in_client.get("/api/system/kill-switch/status")
        assert response.status_code == 200
        body = response.json()
        assert body["engaged"] is False
        assert body["last_event"] is None


class TestKillSwitchEngage:
    def test_requires_reason(self, logged_in_client):
        response = logged_in_client.post("/api/system/kill-switch/engage", json={"reason": "x"})
        assert response.status_code == 422  # min_length=3

    def test_whitespace_only_reason_is_rejected(self, logged_in_client):
        response = logged_in_client.post("/api/system/kill-switch/engage", json={"reason": "   "})
        assert response.status_code == 400

    def test_engages_and_suspends_active_strategies(self, paper_client):
        instance = _create_active_instance(paper_client)
        assert _strategy_status(instance["id"]) == "ACTIVE"

        response = paper_client.post("/api/system/kill-switch/engage", json={"reason": "test manuel"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["engaged"] is True
        assert body["already_engaged"] is False
        assert instance["id"] in body["suspended_strategy_ids"] or str(instance["id"]) in [
            str(i) for i in body["suspended_strategy_ids"]
        ]

        assert _strategy_status(instance["id"]) == "PAUSED"

        status_response = paper_client.get("/api/system/kill-switch/status")
        status_body = status_response.json()
        assert status_body["engaged"] is True
        assert status_body["last_event"]["action"] == "KILL_SWITCH_ENGAGED"
        assert status_body["last_event"]["reason"] == "test manuel"

        events = _audit_events("KILL_SWITCH_ENGAGED")
        assert len(events) == 1
        assert events[0]["detail"]["reason"] == "test manuel"
        assert str(instance["id"]) in events[0]["detail"]["suspended_strategy_ids"]

    def test_does_not_suspend_paused_or_stopped_strategies(self, paper_client):
        instance = _create_active_instance(paper_client)
        response = paper_client.post(f"/api/strategies/instances/{instance['id']}/pause")
        assert response.status_code == 200
        assert _strategy_status(instance["id"]) == "PAUSED"

        response = paper_client.post("/api/system/kill-switch/engage", json={"reason": "test"})
        assert response.status_code == 200
        assert response.json()["suspended_strategy_ids"] == []
        # Toujours PAUSED (déjà le cas avant), jamais réécrit sans raison.
        assert _strategy_status(instance["id"]) == "PAUSED"

    def test_engaging_twice_is_idempotent(self, paper_client):
        instance = _create_active_instance(paper_client)

        first = paper_client.post("/api/system/kill-switch/engage", json={"reason": "premier appel"})
        assert first.status_code == 200
        assert first.json()["already_engaged"] is False

        second = paper_client.post("/api/system/kill-switch/engage", json={"reason": "second appel, devrait être ignoré"})
        assert second.status_code == 200
        assert second.json()["already_engaged"] is True

        # Une seule ligne d'audit ENGAGED, pas deux — le second appel est un
        # no-op complet (aucune stratégie re-suspendue, aucune trace créée).
        events = _audit_events("KILL_SWITCH_ENGAGED")
        assert len(events) == 1
        assert events[0]["detail"]["reason"] == "premier appel"
        assert _strategy_status(instance["id"]) == "PAUSED"

    def test_concurrent_engage_calls_apply_exactly_once(self, paper_client):
        """§checklist "Tests concurrence et idempotence" — N requêtes
        d'engagement simultanées ne doivent produire qu'UNE seule ligne
        d'audit et suspendre chaque stratégie ACTIVE une seule fois."""
        instance = _create_active_instance(paper_client)

        def _engage(i: int):
            return paper_client.post("/api/system/kill-switch/engage", json={"reason": f"concurrent-{i}"})

        with ThreadPoolExecutor(max_workers=5) as pool:
            responses = list(pool.map(_engage, range(5)))

        assert all(r.status_code == 200 for r in responses)
        already_engaged_flags = [r.json()["already_engaged"] for r in responses]
        assert already_engaged_flags.count(False) == 1, "un seul appel doit avoir réellement engagé le kill switch"
        assert already_engaged_flags.count(True) == 4

        events = _audit_events("KILL_SWITCH_ENGAGED")
        assert len(events) == 1
        assert _strategy_status(instance["id"]) == "PAUSED"


class TestKillSwitchDisengage:
    def test_requires_reason(self, logged_in_client):
        response = logged_in_client.post("/api/system/kill-switch/disengage", json={"reason": "x"})
        assert response.status_code == 422

    def test_disengaging_when_not_engaged_is_idempotent(self, logged_in_client):
        response = logged_in_client.post("/api/system/kill-switch/disengage", json={"reason": "rien à faire"})
        assert response.status_code == 200
        body = response.json()
        assert body["engaged"] is False
        assert body["already_disengaged"] is True
        assert _audit_events("KILL_SWITCH_DISENGAGED") == []

    def test_disengage_never_reactivates_strategies(self, paper_client):
        """§checklist "Récupération explicite, jamais automatique" — les
        stratégies suspendues par l'engagement restent PAUSED après le
        désengagement, jamais réactivées automatiquement."""
        instance = _create_active_instance(paper_client)
        assert paper_client.post("/api/system/kill-switch/engage", json={"reason": "test"}).status_code == 200
        assert _strategy_status(instance["id"]) == "PAUSED"

        response = paper_client.post("/api/system/kill-switch/disengage", json={"reason": "fin du test"})
        assert response.status_code == 200
        body = response.json()
        assert body["engaged"] is False
        assert body["already_disengaged"] is False

        # Toujours PAUSED — jamais remis à ACTIVE automatiquement.
        assert _strategy_status(instance["id"]) == "PAUSED"

        status_response = paper_client.get("/api/system/kill-switch/status")
        assert status_response.json()["engaged"] is False

    def test_disengaging_twice_is_idempotent(self, paper_client):
        assert paper_client.post("/api/system/kill-switch/engage", json={"reason": "test"}).status_code == 200

        first = paper_client.post("/api/system/kill-switch/disengage", json={"reason": "premier"})
        assert first.json()["already_disengaged"] is False

        second = paper_client.post("/api/system/kill-switch/disengage", json={"reason": "second, ignoré"})
        assert second.json()["already_disengaged"] is True

        events = _audit_events("KILL_SWITCH_DISENGAGED")
        assert len(events) == 1
        assert events[0]["detail"]["reason"] == "premier"


class TestKillSwitchHistory:
    def test_returns_events_most_recent_first(self, paper_client):
        assert paper_client.post("/api/system/kill-switch/engage", json={"reason": "premier engagement"}).status_code == 200
        assert paper_client.post("/api/system/kill-switch/disengage", json={"reason": "premier désengagement"}).status_code == 200
        assert paper_client.post("/api/system/kill-switch/engage", json={"reason": "second engagement"}).status_code == 200

        response = paper_client.get("/api/system/kill-switch/history")
        assert response.status_code == 200
        events = response.json()["events"]
        assert len(events) == 3
        assert [e["reason"] for e in events] == ["second engagement", "premier désengagement", "premier engagement"]
        assert [e["action"] for e in events] == ["KILL_SWITCH_ENGAGED", "KILL_SWITCH_DISENGAGED", "KILL_SWITCH_ENGAGED"]


class TestKillSwitchHealthIntegration:
    """§B31 "Alerte in-app" — le détail engagé voyage dans la même réponse
    publique déjà pollée par la bannière globale (voir `backend/app/main.py`)."""

    def test_health_reflects_engage_detail(self, paper_client):
        assert paper_client.post("/api/system/kill-switch/engage", json={"reason": "vérification bannière"}).status_code == 200

        response = paper_client.get("/api/system/health")
        assert response.status_code == 200
        body = response.json()
        assert body["trading_kill_switch_engaged"] is True
        assert body["trading_kill_switch_detail"]["reason"] == "vérification bannière"
        assert body["trading_kill_switch_detail"]["actor_user_id"] is not None

    def test_health_detail_is_null_when_not_engaged(self, paper_client):
        response = paper_client.get("/api/system/health")
        body = response.json()
        assert body["trading_kill_switch_engaged"] is False
        assert body["trading_kill_switch_detail"] is None


class TestKillSwitchAlerts:
    """§B20 (D078 levé) — `engage()`/`disengage()` écrivent désormais une
    ligne `Alert` par contexte concerné (voir `_ALERTABLE_CONTEXT_KINDS`,
    `backend/app/kill_switch.py`), en plus de la bannière `KillSwitchBanner`
    déjà existante (D078, poll `/api/system/health`) — les deux coexistent,
    l'une alimente le centre de notifications (`GET /api/alerts`), l'autre
    reste le signal visuel immédiat."""

    def test_engage_writes_one_critical_alert_per_paper_and_replay_context(self, paper_client):
        response = paper_client.post("/api/system/kill-switch/engage", json={"reason": "test alertes"})
        assert response.status_code == 200

        alerts = _kill_switch_alerts()
        assert [a["kind"] for a in alerts] == ["PAPER", "REPLAY"]
        for alert in alerts:
            assert alert["severity"] == "CRITICAL"
            assert alert["is_read"] is False
            assert "test alertes" in alert["message"]

    def test_disengage_writes_info_alert(self, paper_client):
        paper_client.post("/api/system/kill-switch/engage", json={"reason": "avant"})
        paper_client.post("/api/system/kill-switch/disengage", json={"reason": "après vérification"})

        alerts = _kill_switch_alerts()
        info_alerts = [a for a in alerts if a["severity"] == "INFO"]
        assert len(info_alerts) == 2  # un par contexte PAPER/REPLAY
        assert all("après vérification" in a["message"] for a in info_alerts)

    def test_alerts_visible_via_alerts_api_in_active_context(self, paper_client):
        paper_client.post("/api/system/kill-switch/engage", json={"reason": "visible via API"})

        response = paper_client.get("/api/alerts")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] >= 1
        assert any(a["category"] == "kill_switch" and a["severity"] == "CRITICAL" for a in body["alerts"])

        unread = paper_client.get("/api/alerts/unread-count")
        assert unread.json()["unread_count"] >= 1

    def test_idempotent_engage_does_not_duplicate_alerts(self, paper_client):
        paper_client.post("/api/system/kill-switch/engage", json={"reason": "premier"})
        first_count = len(_kill_switch_alerts())
        # §"engager deux fois" — déjà idempotent côté audit (voir
        # `test_engaging_twice_is_idempotent` ci-dessus) ; les alertes
        # suivent la même règle : le second appel est un NO-OP complet.
        paper_client.post("/api/system/kill-switch/engage", json={"reason": "second (no-op)"})
        assert len(_kill_switch_alerts()) == first_count
