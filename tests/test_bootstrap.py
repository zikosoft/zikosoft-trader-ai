"""B22 — `agents/common/bootstrap.py` : heartbeat = readiness métier, pas
seulement "le process boucle" (voir docstring du module). `run_once()` a été
extrait de `run_service()` spécifiquement pour être testable sans boucle
infinie ni `time.sleep` — ces tests l'appellent directement. Contre un vrai
Redis (aucun mock d'infra interne)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

import common.bootstrap as bootstrap  # noqa: E402

from shared.eventbus import heartbeat_key, read_heartbeat  # noqa: E402

SERVICE = "test-bootstrap-service"
_logger = logging.getLogger("test-bootstrap")


@pytest.fixture()
def engine():
    from app.db import engine as _engine  # noqa: PLC0415 — après sys.path, volontaire

    return _engine


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    redis_client.delete(heartbeat_key(SERVICE))
    yield
    redis_client.delete(heartbeat_key(SERVICE))


class TestRunOnce:
    def test_successful_tick_publishes_healthy(self, engine, redis_client):
        bootstrap.run_once(SERVICE, lambda e, r: None, engine, redis_client, ttl_seconds=15, logger=_logger)
        assert read_heartbeat(redis_client, SERVICE)["state"] == "HEALTHY"

    def test_failing_tick_publishes_degraded_not_healthy(self, engine, redis_client):
        def _boom(e, r):
            raise RuntimeError("tick métier en échec")

        # Ne doit jamais lever — un tick en échec ne doit pas tuer le service
        # (même discipline que l'ancien comportement, inchangée par B22).
        bootstrap.run_once(SERVICE, _boom, engine, redis_client, ttl_seconds=15, logger=_logger)
        assert read_heartbeat(redis_client, SERVICE)["state"] == "DEGRADED"

    def test_recovers_to_healthy_after_a_failed_tick(self, engine, redis_client):
        calls = {"n": 0}

        def _flaky(e, r):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("échec transitoire")

        bootstrap.run_once(SERVICE, _flaky, engine, redis_client, ttl_seconds=15, logger=_logger)
        assert read_heartbeat(redis_client, SERVICE)["state"] == "DEGRADED"
        bootstrap.run_once(SERVICE, _flaky, engine, redis_client, ttl_seconds=15, logger=_logger)
        assert read_heartbeat(redis_client, SERVICE)["state"] == "HEALTHY"

    def test_engine_and_redis_client_passed_through_to_tick(self, engine, redis_client):
        seen = {}

        def _capture(e, r):
            seen["engine"] = e
            seen["redis"] = r

        bootstrap.run_once(SERVICE, _capture, engine, redis_client, ttl_seconds=15, logger=_logger)
        assert seen["engine"] is engine
        assert seen["redis"] is redis_client


class TestTickIntervalOverride:
    """§B10 checklist "fréquence d'analyse configurable par variable
    d'environnement" — trouvé absent le 28/08 (audit B10), corrigé par
    `_tick_interval_override`. Convention testée ici :
    `<SERVICE_NAME>_TICK_INTERVAL_SECONDS` (tirets -> underscores, majuscules)."""

    def test_no_env_var_returns_none(self, monkeypatch):
        monkeypatch.delenv("MARKET_AGENT_TICK_INTERVAL_SECONDS", raising=False)
        assert bootstrap._tick_interval_override("market-agent") is None

    def test_valid_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("MARKET_AGENT_TICK_INTERVAL_SECONDS", "120")
        assert bootstrap._tick_interval_override("market-agent") == 120.0

    def test_invalid_env_var_ignored_not_a_crash(self, monkeypatch):
        monkeypatch.setenv("MARKET_AGENT_TICK_INTERVAL_SECONDS", "not-a-number")
        assert bootstrap._tick_interval_override("market-agent") is None

    def test_zero_or_negative_ignored(self, monkeypatch):
        monkeypatch.setenv("MARKET_AGENT_TICK_INTERVAL_SECONDS", "0")
        assert bootstrap._tick_interval_override("market-agent") is None
        monkeypatch.setenv("MARKET_AGENT_TICK_INTERVAL_SECONDS", "-5")
        assert bootstrap._tick_interval_override("market-agent") is None

    def test_run_service_applies_override(self, engine, redis_client, monkeypatch):
        """Bout en bout : `run_service` dort effectivement `interval_seconds`
        secondes issues de la variable d'environnement, pas la valeur par
        défaut codée en dur par l'appelant. Le `tick()` factice demande
        l'arrêt après sa première exécution pour que la boucle ne tourne
        qu'une seule fois (§même technique que `TestRunServiceShutdown`)."""
        monkeypatch.setattr(bootstrap, "_shutdown_requested", False)
        monkeypatch.setattr(bootstrap, "build_engine", lambda: engine)
        monkeypatch.setattr(bootstrap, "build_redis_client", lambda: redis_client)
        monkeypatch.setenv(f"{SERVICE.upper().replace('-', '_')}_TICK_INTERVAL_SECONDS", "42")
        captured = {}

        def _fake_sleep(seconds):
            captured["seconds"] = seconds
            bootstrap._shutdown_requested = True

        monkeypatch.setattr(bootstrap.time, "sleep", _fake_sleep)
        bootstrap.run_service(SERVICE, lambda e, r: None)
        assert captured["seconds"] == 42.0


class TestHeartbeatTtlOverride:
    """A long, bounded Market Agent MCP tick must not create a false outage."""

    def test_no_env_var_returns_none(self, monkeypatch):
        monkeypatch.delenv("MARKET_AGENT_HEARTBEAT_TTL_SECONDS", raising=False)
        assert bootstrap._heartbeat_ttl_override("market-agent") is None

    def test_valid_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("MARKET_AGENT_HEARTBEAT_TTL_SECONDS", "60")
        assert bootstrap._heartbeat_ttl_override("market-agent") == 60

    def test_invalid_or_non_positive_value_is_ignored(self, monkeypatch):
        monkeypatch.setenv("MARKET_AGENT_HEARTBEAT_TTL_SECONDS", "not-a-number")
        assert bootstrap._heartbeat_ttl_override("market-agent") is None
        monkeypatch.setenv("MARKET_AGENT_HEARTBEAT_TTL_SECONDS", "0")
        assert bootstrap._heartbeat_ttl_override("market-agent") is None
        monkeypatch.setenv("MARKET_AGENT_HEARTBEAT_TTL_SECONDS", "-1")
        assert bootstrap._heartbeat_ttl_override("market-agent") is None


class TestRunServiceShutdown:
    def test_stopped_heartbeat_published_on_shutdown(self, redis_client, monkeypatch):
        """§checklist B22 "États STOPPED" : simule un arrêt déjà demandé
        AVANT que la boucle ne démarre (équivalent à un SIGTERM reçu très
        tôt) — la boucle ne doit exécuter aucune itération mais doit tout de
        même publier l'état STOPPED avant de sortir, pour que le Watchdog
        distingue cet arrêt volontaire d'une vraie déconnexion."""
        monkeypatch.setattr(bootstrap, "_shutdown_requested", True)
        monkeypatch.setattr(bootstrap, "build_redis_client", lambda: redis_client)
        # DATABASE_URL est déjà résolu vers le Postgres local par conftest.py
        # (setdefault avant tout import) — build_engine() réutilise le même
        # DSN que `app.db.engine`, inutile de le monkeypatcher séparément.

        called = {"n": 0}
        bootstrap.run_service(SERVICE, lambda e, r: called.__setitem__("n", called["n"] + 1))

        assert called["n"] == 0  # aucune itération exécutée
        assert read_heartbeat(redis_client, SERVICE)["state"] == "STOPPED"
