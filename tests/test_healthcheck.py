"""B22 — `agents/common/healthcheck.py` (script `HEALTHCHECK` Docker des
agents/workers). Contre un vrai Redis, aucun mock d'infra interne."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

from common.healthcheck import main as healthcheck_main  # noqa: E402

from shared.eventbus import heartbeat_key, publish_heartbeat  # noqa: E402

SERVICE = "test-healthcheck-service"


@pytest.fixture(autouse=True)
def _clean_state(redis_client, monkeypatch):
    redis_client.delete(heartbeat_key(SERVICE))
    monkeypatch.setenv("SERVICE_NAME", SERVICE)
    monkeypatch.setenv("REDIS_URL", os.environ["REDIS_URL"])
    yield
    redis_client.delete(heartbeat_key(SERVICE))


class TestHealthcheckMain:
    def test_healthy_is_exit_0(self, redis_client):
        publish_heartbeat(redis_client, SERVICE, state="HEALTHY", ttl_seconds=15)
        assert healthcheck_main() == 0

    def test_degraded_is_still_exit_0(self, redis_client):
        """§docstring `healthcheck.py` — DEGRADED = conteneur vivant qui
        boucle, PAS un conteneur mort : Docker ne doit pas tenter de le
        redémarrer pour un simple échec métier transitoire."""
        publish_heartbeat(redis_client, SERVICE, state="DEGRADED", ttl_seconds=15)
        assert healthcheck_main() == 0

    def test_stopped_is_exit_1(self, redis_client):
        publish_heartbeat(redis_client, SERVICE, state="STOPPED", ttl_seconds=15)
        assert healthcheck_main() == 1

    def test_missing_heartbeat_is_exit_1(self):
        assert healthcheck_main() == 1

    def test_missing_service_name_env_is_exit_1(self, monkeypatch):
        monkeypatch.delenv("SERVICE_NAME", raising=False)
        assert healthcheck_main() == 1
