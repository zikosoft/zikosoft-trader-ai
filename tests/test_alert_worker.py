
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

import alert_worker.main as aw  # noqa: E402
from sqlalchemy import text  # noqa: E402

from shared.eventbus import publish_event  # noqa: E402
from shared.events import EventEnvelope, Streams  # noqa: E402


@pytest.fixture()
def engine():
    from app.db import engine as _engine  # noqa: PLC0415 — après sys.path, volontaire

    return _engine


@pytest.fixture(autouse=True)
def _clean_state(engine, redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM alerts WHERE category = 'system_health'"))
        conn.commit()
    redis_client.delete(Streams.SYSTEM_EVENTS, Streams.ALERT_EVENTS)
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM alerts WHERE category = 'system_health'"))
        conn.commit()
    redis_client.delete(Streams.SYSTEM_EVENTS, Streams.ALERT_EVENTS)


def _health_changed_envelope(
    *, service_name: str = "market-agent", previous_state: str | None, new_state: str,
    is_incident: bool, is_recovery: bool, event_id: uuid.UUID | None = None,
) -> EventEnvelope:
    kwargs = {"event_id": event_id} if event_id is not None else {}
    return EventEnvelope(
        event_type="system.service.health_changed",
        correlation_id=uuid.uuid4(),
        execution_context_id=None,
        payload={
            "service_name": service_name,
            "previous_state": previous_state,
            "new_state": new_state,
            "is_incident": is_incident,
            "is_recovery": is_recovery,
        },
        **kwargs,
    )


def _all_context_ids(engine) -> set[uuid.UUID]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT id FROM execution_contexts"))}


def _system_health_alerts(engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM alerts WHERE category = 'system_health' ORDER BY execution_context_id")
        ).mappings().all()
    return [dict(r) for r in rows]


class TestIncidentDispatch:
    def test_disconnected_incident_creates_one_critical_alert_per_execution_context(self, engine, redis_client):
        envelope = _health_changed_envelope(previous_state="HEALTHY", new_state="DISCONNECTED", is_incident=True, is_recovery=False)
        publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)

        aw.tick(engine, redis_client)

        alerts = _system_health_alerts(engine)
        assert {a["execution_context_id"] for a in alerts} == _all_context_ids(engine)
        assert all(a["severity"] == "CRITICAL" for a in alerts)
        assert all(a["is_read"] is False for a in alerts)
        assert all("market-agent" in a["title"] for a in alerts)

    def test_degraded_incident_creates_warning_alert(self, engine, redis_client):
        envelope = _health_changed_envelope(previous_state="HEALTHY", new_state="DEGRADED", is_incident=True, is_recovery=False)
        publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)

        aw.tick(engine, redis_client)

        alerts = _system_health_alerts(engine)
        assert alerts
        assert all(a["severity"] == "WARNING" for a in alerts)

    def test_recovery_creates_info_alert(self, engine, redis_client):
        envelope = _health_changed_envelope(previous_state="DISCONNECTED", new_state="HEALTHY", is_incident=False, is_recovery=True)
        publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)

        aw.tick(engine, redis_client)

        alerts = _system_health_alerts(engine)
        assert alerts
        assert all(a["severity"] == "INFO" for a in alerts)
        assert all("rétabli" in a["title"] for a in alerts)

    def test_neutral_transition_creates_no_alert(self, engine, redis_client):
        """§checklist — `STARTING -> HEALTHY` au premier démarrage n'est ni
        un incident ni une récupération (voir Watchdog, `is_incident`/
        `is_recovery` tous deux `False`) : aucun bruit de boot."""
        envelope = _health_changed_envelope(previous_state="STARTING", new_state="HEALTHY", is_incident=False, is_recovery=False)
        publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)

        aw.tick(engine, redis_client)

        assert _system_health_alerts(engine) == []

    def test_other_event_types_on_same_stream_are_ignored(self, engine, redis_client):
        envelope = EventEnvelope(
            event_type="something.else.entirely",
            correlation_id=uuid.uuid4(),
            execution_context_id=None,
            payload={},
        )
        publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)

        aw.tick(engine, redis_client)  # ne doit pas lever, juste ignorer

        assert _system_health_alerts(engine) == []


class TestDeduplication:
    def test_redelivering_the_same_event_id_does_not_duplicate_alerts(self, engine, redis_client):
        fixed_id = uuid.uuid4()
        envelope = _health_changed_envelope(
            previous_state="HEALTHY", new_state="DISCONNECTED", is_incident=True, is_recovery=False, event_id=fixed_id
        )
        publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)
        aw.tick(engine, redis_client)
        first_count = len(_system_health_alerts(engine))
        assert first_count > 0

        # Republie la MÊME enveloppe (même `event_id`, donc même
        # `dedup_key` par contexte) — simule une redistribution Redis
        # Streams après crash avant `ack` (§checklist "Déduplication").
        publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)
        aw.tick(engine, redis_client)

        assert len(_system_health_alerts(engine)) == first_count


class TestAlertEventsPublication:
    def test_publishes_one_alert_created_event_per_context(self, engine, redis_client):
        envelope = _health_changed_envelope(previous_state="HEALTHY", new_state="DISCONNECTED", is_incident=True, is_recovery=False)
        publish_event(redis_client, Streams.SYSTEM_EVENTS, envelope)

        aw.tick(engine, redis_client)

        entries = redis_client.xrange(Streams.ALERT_EVENTS, min="-", max="+")
        assert len(entries) == len(_all_context_ids(engine))
