"""B22 — `workers/watchdog/main.py`. Intégration réelle contre PostgreSQL et
Redis (aucun mock d'infra interne) — même discipline que
`test_portfolio_worker.py` (B18) : ce module ne publie que sur `system.events`
(Redis Streams) et n'a pas besoin du SDK `mcp`, ces tests tournent sous
`.venv` (backend), pas `.venv-agents`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

import watchdog.main as wd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from shared.eventbus import heartbeat_key, publish_heartbeat  # noqa: E402
from shared.events import Streams  # noqa: E402
from shared.watchdog import ESSENTIAL_SERVICES  # noqa: E402

AGENT_SERVICE = "market-agent"  # un des 6 services essentiels basés heartbeat


@pytest.fixture()
def engine():
    from app.db import engine as _engine  # noqa: PLC0415 — après sys.path, volontaire

    return _engine


@pytest.fixture(autouse=True)
def _clean_state(engine, redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM service_health_events"))
        conn.commit()
    redis_client.delete(Streams.SYSTEM_EVENTS)
    for service in ESSENTIAL_SERVICES:
        redis_client.delete(heartbeat_key(service))
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM service_health_events"))
        conn.commit()
    redis_client.delete(Streams.SYSTEM_EVENTS)
    for service in ESSENTIAL_SERVICES:
        redis_client.delete(heartbeat_key(service))


def _drain(redis_client, stream: str) -> list[dict]:
    entries = redis_client.xrange(stream, min="-", max="+")
    out = []
    for _mid, fields in entries:
        raw = fields.get(b"envelope") or fields.get("envelope")
        if isinstance(raw, bytes):
            raw = raw.decode()
        out.append(json.loads(raw))
    return out


def _latest_rows(engine) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT ON (service_name) service_name, state, detail, last_heartbeat_at "
                "FROM service_health_events ORDER BY service_name, created_at DESC"
            )
        ).mappings().all()
    return {row["service_name"]: dict(row) for row in rows}


class TestPostgresRedisChecks:
    def test_postgres_and_redis_healthy_first_tick_records_transition(self, engine, redis_client):
        wd.tick(engine, redis_client)
        rows = _latest_rows(engine)
        assert rows["postgres"]["state"] == "HEALTHY"
        assert rows["redis"]["state"] == "HEALTHY"

        events = _drain(redis_client, Streams.SYSTEM_EVENTS)
        service_names = {e["payload"]["service_name"] for e in events}
        assert "postgres" in service_names
        assert "redis" in service_names


class TestHeartbeatServices:
    def test_never_observed_service_is_starting(self, engine, redis_client):
        wd.tick(engine, redis_client)
        rows = _latest_rows(engine)
        assert rows[AGENT_SERVICE]["state"] == "STARTING"

    def test_starting_service_transitions_to_healthy_once_heartbeat_appears(self, engine, redis_client):
        wd.tick(engine, redis_client)  # observe STARTING, l'enregistre
        publish_heartbeat(redis_client, AGENT_SERVICE, state="HEALTHY", ttl_seconds=15)
        wd.tick(engine, redis_client)
        rows = _latest_rows(engine)
        assert rows[AGENT_SERVICE]["state"] == "HEALTHY"
        assert rows[AGENT_SERVICE]["detail"]["previous_state"] == "STARTING"

    def test_degraded_heartbeat_is_recorded_as_incident(self, engine, redis_client):
        publish_heartbeat(redis_client, AGENT_SERVICE, state="DEGRADED", ttl_seconds=15)
        wd.tick(engine, redis_client)
        rows = _latest_rows(engine)
        assert rows[AGENT_SERVICE]["state"] == "DEGRADED"

        events = _drain(redis_client, Streams.SYSTEM_EVENTS)
        payload = next(e["payload"] for e in events if e["payload"]["service_name"] == AGENT_SERVICE)
        assert payload["is_incident"] is True
        assert payload["is_recovery"] is False

    def test_lost_heartbeat_after_being_seen_is_disconnected(self, engine, redis_client):
        publish_heartbeat(redis_client, AGENT_SERVICE, state="HEALTHY", ttl_seconds=15)
        wd.tick(engine, redis_client)  # observe HEALTHY, l'enregistre

        redis_client.delete(heartbeat_key(AGENT_SERVICE))  # simule l'expiration/la panne
        wd.tick(engine, redis_client)
        rows = _latest_rows(engine)
        assert rows[AGENT_SERVICE]["state"] == "DISCONNECTED"

        events = _drain(redis_client, Streams.SYSTEM_EVENTS)
        payload = [e["payload"] for e in events if e["payload"]["service_name"] == AGENT_SERVICE][-1]
        assert payload["is_incident"] is True

    def test_recovery_after_disconnection_is_flagged(self, engine, redis_client):
        publish_heartbeat(redis_client, AGENT_SERVICE, state="HEALTHY", ttl_seconds=15)
        wd.tick(engine, redis_client)
        redis_client.delete(heartbeat_key(AGENT_SERVICE))
        wd.tick(engine, redis_client)  # -> DISCONNECTED

        publish_heartbeat(redis_client, AGENT_SERVICE, state="HEALTHY", ttl_seconds=15)
        wd.tick(engine, redis_client)  # -> HEALTHY à nouveau
        rows = _latest_rows(engine)
        assert rows[AGENT_SERVICE]["state"] == "HEALTHY"

        events = _drain(redis_client, Streams.SYSTEM_EVENTS)
        payload = [e["payload"] for e in events if e["payload"]["service_name"] == AGENT_SERVICE][-1]
        assert payload["is_recovery"] is True
        assert payload["is_incident"] is False

    def test_stopped_is_neither_incident_nor_recovery(self, engine, redis_client):
        """§checklist B22 "États STOPPED" — un arrêt propre (SIGTERM,
        `docker compose down`) n'est ni un incident ni une récupération,
        contrairement à une vraie déconnexion."""
        publish_heartbeat(redis_client, AGENT_SERVICE, state="HEALTHY", ttl_seconds=15)
        wd.tick(engine, redis_client)

        publish_heartbeat(redis_client, AGENT_SERVICE, state="STOPPED", ttl_seconds=15)
        wd.tick(engine, redis_client)
        rows = _latest_rows(engine)
        assert rows[AGENT_SERVICE]["state"] == "STOPPED"

        events = _drain(redis_client, Streams.SYSTEM_EVENTS)
        payload = [e["payload"] for e in events if e["payload"]["service_name"] == AGENT_SERVICE][-1]
        assert payload["is_incident"] is False
        assert payload["is_recovery"] is False


class TestDeduplication:
    def test_unchanged_state_does_not_write_or_publish_again(self, engine, redis_client):
        publish_heartbeat(redis_client, AGENT_SERVICE, state="HEALTHY", ttl_seconds=15)
        wd.tick(engine, redis_client)
        with engine.connect() as conn:
            count_after_first = conn.execute(text("SELECT COUNT(*) FROM service_health_events")).scalar_one()
        events_after_first = len(_drain(redis_client, Streams.SYSTEM_EVENTS))

        # État inchangé pour TOUS les services (heartbeat republié à
        # l'identique, postgres/redis toujours HEALTHY) -> aucun nouveau tick
        # ne doit rien ajouter.
        publish_heartbeat(redis_client, AGENT_SERVICE, state="HEALTHY", ttl_seconds=15)
        wd.tick(engine, redis_client)
        with engine.connect() as conn:
            count_after_second = conn.execute(text("SELECT COUNT(*) FROM service_health_events")).scalar_one()
        events_after_second = len(_drain(redis_client, Streams.SYSTEM_EVENTS))

        assert count_after_second == count_after_first
        assert events_after_second == events_after_first


class TestEventEnvelope:
    def test_published_event_has_no_execution_context(self, engine, redis_client):
        wd.tick(engine, redis_client)
        events = _drain(redis_client, Streams.SYSTEM_EVENTS)
        assert events, "au moins un événement attendu au premier tick"
        for event in events:
            assert event["execution_context_id"] is None
        assert events[0]["event_type"] == "system.service.health_changed"

    def test_all_nine_essential_services_observed_on_first_tick(self, engine, redis_client):
        wd.tick(engine, redis_client)
        rows = _latest_rows(engine)
        assert set(rows.keys()) == set(ESSENTIAL_SERVICES)
