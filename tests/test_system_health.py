"""B22 — `GET /api/system/health` (agrégation, voir `backend/app/main.py`).
Contre PostgreSQL/Redis réels et l'app FastAPI réelle (TestClient), aucun
mock d'infra interne — pas d'authentification requise (même route que
`/health`, socle de diagnostic, voir B01-B04)."""

from __future__ import annotations

import uuid

import pytest
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

from shared.risk_governance import TRADING_KILL_SWITCH_REDIS_KEY
from shared.watchdog import ESSENTIAL_SERVICES


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM service_health_events"))
        conn.commit()
    redis_client.delete(TRADING_KILL_SWITCH_REDIS_KEY)
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM service_health_events"))
        conn.commit()
    redis_client.delete(TRADING_KILL_SWITCH_REDIS_KEY)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _insert_health_event(*, service_name: str, state: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO service_health_events (id, service_name, state, detail, last_heartbeat_at) "
                "VALUES (:id, :service_name, :state, '{}'::jsonb, now())"
            ),
            {"id": uuid.uuid4(), "service_name": service_name, "state": state},
        )


class TestSystemHealth:
    def test_postgres_and_redis_always_live_checked(self, client):
        response = client.get("/api/system/health")
        assert response.status_code == 200
        body = response.json()
        assert body["checks"]["postgres"]["status"] == "HEALTHY"
        assert body["checks"]["redis"]["status"] == "HEALTHY"
        assert "latency_ms" in body["checks"]["postgres"]

    def test_service_never_observed_by_watchdog_is_starting(self, client):
        response = client.get("/api/system/health")
        body = response.json()
        for service in ESSENTIAL_SERVICES:
            if service in ("postgres", "redis"):
                continue
            assert body["checks"][service]["status"] == "STARTING"
        assert body["status"] == "DEGRADED"  # au moins un service en STARTING

    def test_all_healthy_reports_overall_healthy(self, client):
        for service in ESSENTIAL_SERVICES:
            if service in ("postgres", "redis"):
                continue
            _insert_health_event(service_name=service, state="HEALTHY")

        response = client.get("/api/system/health")
        body = response.json()
        assert body["status"] == "HEALTHY"
        for service in ESSENTIAL_SERVICES:
            if service in ("postgres", "redis"):
                continue
            assert body["checks"][service]["status"] == "HEALTHY"
            assert body["checks"][service]["last_heartbeat_at"] is not None

    def test_one_degraded_service_makes_overall_degraded(self, client):
        for service in ESSENTIAL_SERVICES:
            if service in ("postgres", "redis"):
                continue
            _insert_health_event(service_name=service, state="HEALTHY")
        _insert_health_event(service_name="risk-engine", state="DEGRADED")

        response = client.get("/api/system/health")
        body = response.json()
        assert body["status"] == "DEGRADED"
        assert body["checks"]["risk-engine"]["status"] == "DEGRADED"

    def test_only_latest_state_per_service_counts(self, client):
        _insert_health_event(service_name="order-worker", state="DEGRADED")
        _insert_health_event(service_name="order-worker", state="HEALTHY")

        response = client.get("/api/system/health")
        body = response.json()
        assert body["checks"]["order-worker"]["status"] == "HEALTHY"

    def test_plain_health_endpoint_unaffected(self, client):
        """`/health` reste un simple ping de process, indépendant de
        l'agrégation Watchdog (voir docstring de `system_health()`)."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "backend-api"}


class TestTradingKillSwitch:
    """§B26 "Kill switch" — le dashboard lit l'état RÉEL du flag déjà
    appliqué par le Risk Engine (B15, `shared/shared/risk_governance.py`),
    exposé ici en lecture seule uniquement (pas de toggle — voir docstring
    de `system_health()`)."""

    def test_defaults_to_not_engaged(self, client):
        response = client.get("/api/system/health")
        assert response.json()["trading_kill_switch_engaged"] is False

    def test_reflects_engaged_flag(self, client, redis_client):
        redis_client.set(TRADING_KILL_SWITCH_REDIS_KEY, "true")
        response = client.get("/api/system/health")
        assert response.json()["trading_kill_switch_engaged"] is True

    def test_not_part_of_incident_checks(self, client, redis_client):
        """Un kill switch engagé est un état de sécurité intentionnel, pas
        un incident (D056) — ne doit jamais faire basculer `status` ou
        apparaître dans `checks`, même quand tous les autres services sont
        par ailleurs `HEALTHY`."""
        for service in ESSENTIAL_SERVICES:
            if service in ("postgres", "redis"):
                continue
            _insert_health_event(service_name=service, state="HEALTHY")
        redis_client.set(TRADING_KILL_SWITCH_REDIS_KEY, "true")

        response = client.get("/api/system/health")
        body = response.json()
        assert body["status"] == "HEALTHY"
        assert body["trading_kill_switch_engaged"] is True
        assert "trading_kill_switch_engaged" not in body["checks"]
        assert all("kill_switch" not in k for k in body["checks"])
