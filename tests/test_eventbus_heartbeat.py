"""B22 — `shared/shared/eventbus.py::publish_heartbeat`/`read_heartbeat`.
Contre un vrai Redis (fixture `redis_client`, voir conftest.py), aucun mock —
même discipline que le reste du projet pour notre propre infra."""

from __future__ import annotations

import json

import pytest

from shared.eventbus import heartbeat_key, publish_heartbeat, read_heartbeat

SERVICE = "test-watchdog-service"


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    redis_client.delete(heartbeat_key(SERVICE))
    yield
    redis_client.delete(heartbeat_key(SERVICE))


class TestPublishReadHeartbeat:
    def test_round_trip_healthy(self, redis_client):
        publish_heartbeat(redis_client, SERVICE, state="HEALTHY", ttl_seconds=15)
        value = read_heartbeat(redis_client, SERVICE)
        assert value["state"] == "HEALTHY"
        assert value["at"]  # horodatage ISO8601 non vide

    def test_round_trip_degraded(self, redis_client):
        publish_heartbeat(redis_client, SERVICE, state="DEGRADED", ttl_seconds=15)
        assert read_heartbeat(redis_client, SERVICE)["state"] == "DEGRADED"

    def test_round_trip_stopped(self, redis_client):
        publish_heartbeat(redis_client, SERVICE, state="STOPPED", ttl_seconds=15)
        assert read_heartbeat(redis_client, SERVICE)["state"] == "STOPPED"

    def test_default_state_is_healthy(self, redis_client):
        publish_heartbeat(redis_client, SERVICE, ttl_seconds=15)
        assert read_heartbeat(redis_client, SERVICE)["state"] == "HEALTHY"

    def test_unknown_state_rejected(self, redis_client):
        with pytest.raises(ValueError, match="état de heartbeat inconnu"):
            publish_heartbeat(redis_client, SERVICE, state="BOGUS", ttl_seconds=15)

    def test_missing_key_returns_none(self, redis_client):
        assert read_heartbeat(redis_client, SERVICE) is None

    def test_ttl_is_set(self, redis_client):
        publish_heartbeat(redis_client, SERVICE, ttl_seconds=15)
        ttl = redis_client.ttl(heartbeat_key(SERVICE))
        assert 0 < ttl <= 15

    def test_expired_key_returns_none(self, redis_client):
        import time

        publish_heartbeat(redis_client, SERVICE, ttl_seconds=15)
        redis_client.pexpire(heartbeat_key(SERVICE), 1)  # force l'expiration immédiate sans dormir 15s
        time.sleep(0.05)
        assert read_heartbeat(redis_client, SERVICE) is None

    def test_legacy_plain_string_still_readable(self, redis_client):
        """Compat rétro : une clé encore écrite au format pré-B22 (chaîne
        littérale "HEALTHY", jamais JSON) reste lisible plutôt que de casser
        un déploiement en cours de rolling-update image par image."""
        redis_client.set(heartbeat_key(SERVICE), "HEALTHY", ex=15)
        value = read_heartbeat(redis_client, SERVICE)
        assert value == {"state": "HEALTHY", "at": ""}

    def test_legacy_unknown_plain_string_returns_none(self, redis_client):
        redis_client.set(heartbeat_key(SERVICE), "GARBAGE", ex=15)
        assert read_heartbeat(redis_client, SERVICE) is None

    def test_malformed_json_returns_none(self, redis_client):
        redis_client.set(heartbeat_key(SERVICE), json.dumps([1, 2, 3]), ex=15)
        assert read_heartbeat(redis_client, SERVICE) is None
