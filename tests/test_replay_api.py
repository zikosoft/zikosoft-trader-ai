"""B19 (Étape A) — `/api/replay/*`. Contre PostgreSQL/Redis réels et l'app
FastAPI réelle (TestClient), même principe que `test_portfolio_api.py` :
aucun mock de notre propre infra. Le dataset lui-même est construit en
mémoire puis sauvegardé dans un `tmp_path` (pas de vrai dataset ici — voir
`scripts/fetch_replay_dataset.py`, à faire tourner par Zac lui-même), et
`settings.replay_dataset_path` est monkeypatché pour pointer dessus."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.config import settings
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

from shared.replay_market_data import build_dataset, save_dataset

TS = [f"2026-08-31T13:{m:02d}:00+00:00" for m in range(30, 33)]  # 3 minutes


def _bars_by_symbol(symbols=("AAPL", "MSFT", "SPY"), timestamps=TS, base_price=100.0):
    out = {}
    for i, symbol in enumerate(symbols):
        out[symbol] = {
            ts: {
                "open": base_price + i,
                "high": base_price + i + 1,
                "low": base_price + i - 1,
                "close": base_price + i + 0.5,
                "volume": 1000.0,
            }
            for ts in timestamps
        }
    return out


def _crossover_bars_by_symbol() -> dict[str, dict[str, dict]]:
    """22 deterministic one-minute bars that trigger the existing MA(9/21)
    strategy exactly once on the final AAPL candle."""
    start = datetime(2026, 8, 31, 13, 30, tzinfo=UTC)
    timestamps = [(start + timedelta(minutes=i)).isoformat() for i in range(22)]
    closes = [100.0] * 21 + [104.0]
    return {
        symbol: {
            timestamp: {
                "open": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1000.0,
            }
            for timestamp, close in zip(timestamps, closes, strict=True)
        }
        for symbol in ("AAPL", "MSFT", "SPY")
    }


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
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
def replay_client(logged_in_client):
    response = logged_in_client.post("/api/contexts/select", json={"kind": "REPLAY"})
    assert response.status_code == 200
    return logged_in_client


@pytest.fixture()
def paper_client(logged_in_client):
    response = logged_in_client.post("/api/contexts/select", json={"kind": "PAPER"})
    assert response.status_code == 200
    return logged_in_client


@pytest.fixture()
def dataset_path(tmp_path, monkeypatch):
    path = tmp_path / "dataset.json"
    dataset = build_dataset(
        dataset_id="test-2026-08-31", trading_day="2026-08-31", timezone="America/New_York",
        bars_by_symbol=_bars_by_symbol(),
    )
    save_dataset(dataset, path)
    monkeypatch.setattr(settings, "replay_dataset_path", str(path))
    return path


class TestAuthAndContextRequired:
    def test_dataset_requires_auth(self, client):
        response = client.get("/api/replay/dataset")
        assert response.status_code == 401

    def test_session_reset_requires_auth(self, client):
        response = client.post("/api/replay/session/reset")
        assert response.status_code == 401

    def test_options_preview_requires_auth(self, client):
        response = client.get("/api/replay/options-preview")
        assert response.status_code == 401

    def test_session_reset_requires_replay_context(self, paper_client, dataset_path):
        response = paper_client.post("/api/replay/session/reset")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_session_advance_requires_replay_context_even_without_dataset(self, paper_client):
        # §isolation d'abord : même sans dataset sur disque, un contexte
        # Paper ne doit jamais atteindre le chargement du dataset Replay.
        response = paper_client.post("/api/replay/session/advance")
        assert response.status_code == 400

    def test_options_preview_requires_replay_context_even_without_dataset(self, paper_client):
        response = paper_client.get("/api/replay/options-preview")
        assert response.status_code == 400

    def test_no_active_context_at_all_is_rejected(self, logged_in_client, dataset_path):
        response = logged_in_client.get("/api/replay/session")
        assert response.status_code == 400


class TestDatasetInfo:
    def test_404_when_no_dataset_file(self, replay_client, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "replay_dataset_path", str(tmp_path / "does_not_exist.json"))
        response = replay_client.get("/api/replay/dataset")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_dataset_metadata(self, replay_client, dataset_path):
        response = replay_client.get("/api/replay/dataset")
        assert response.status_code == 200
        body = response.json()
        assert body["dataset_id"] == "test-2026-08-31"
        assert body["symbols"] == ["AAPL", "MSFT", "SPY"]
        assert body["total_bars"] == 3
        assert len(body["checksum"]) == 64


class TestSessionFlow:
    def test_session_before_reset_is_404(self, replay_client, dataset_path):
        response = replay_client.get("/api/replay/session")
        assert response.status_code == 404

    def test_reset_starts_before_first_bar(self, replay_client, dataset_path):
        response = replay_client.post("/api/replay/session/reset")
        assert response.status_code == 200
        body = response.json()
        assert body["current_index"] == -1
        assert body["current_bars"] == {}
        assert body["is_finished"] is False
        assert body["total_bars"] == 3

    def test_advance_moves_one_bar_and_persists(self, replay_client, dataset_path):
        replay_client.post("/api/replay/session/reset")
        response = replay_client.post("/api/replay/session/advance")
        assert response.status_code == 200
        body = response.json()
        assert body["current_index"] == 0
        assert set(body["current_bars"]) == {"AAPL", "MSFT", "SPY"}
        assert body["current_timestamp"] == TS[0]

        # §statelessness — une nouvelle requête (nouveau provider reconstruit
        # côté serveur) doit retrouver exactement la même position via Redis.
        follow_up = replay_client.get("/api/replay/session")
        assert follow_up.status_code == 200
        assert follow_up.json()["current_index"] == 0
        assert follow_up.json()["current_bars"] == body["current_bars"]

    def test_advance_without_prior_reset_starts_fresh(self, replay_client, dataset_path):
        response = replay_client.post("/api/replay/session/advance")
        assert response.status_code == 200
        assert response.json()["current_index"] == 0

    def test_advance_past_the_end_stays_finished_never_errors(self, replay_client, dataset_path):
        replay_client.post("/api/replay/session/reset")
        for _ in range(3):
            response = replay_client.post("/api/replay/session/advance")
            assert response.status_code == 200
        assert response.json()["is_finished"] is True

        one_more = replay_client.post("/api/replay/session/advance")
        assert one_more.status_code == 200
        assert one_more.json()["is_finished"] is True
        assert one_more.json()["current_index"] == 2  # inchangé, plus rien à avancer

    def test_two_identical_replays_produce_identical_data(self, replay_client, dataset_path):
        """§checklist "Deux replays identiques reçoivent les mêmes données"."""
        first_run = []
        replay_client.post("/api/replay/session/reset")
        for _ in range(3):
            first_run.append(replay_client.post("/api/replay/session/advance").json()["current_bars"])

        second_run = []
        replay_client.post("/api/replay/session/reset")
        for _ in range(3):
            second_run.append(replay_client.post("/api/replay/session/advance").json()["current_bars"])

        assert first_run == second_run

    def test_dataset_regenerated_mid_session_restarts_cleanly(self, replay_client, dataset_path, tmp_path):
        """Si `fetch_replay_dataset.py` est rejoué avec un nouveau contenu
        entre deux requêtes (nouveau `dataset_id`), la session précédente
        (index sur l'ancien dataset) doit être ignorée plutôt que provoquer
        un `seek()` hors bornes ou des données incohérentes."""
        replay_client.post("/api/replay/session/reset")
        replay_client.post("/api/replay/session/advance")

        new_dataset = build_dataset(
            dataset_id="test-2026-09-01", trading_day="2026-09-01", timezone="America/New_York",
            bars_by_symbol=_bars_by_symbol(timestamps=TS[:2]),
        )
        save_dataset(new_dataset, dataset_path)

        response = replay_client.post("/api/replay/session/advance")
        assert response.status_code == 200
        body = response.json()
        assert body["dataset_id"] == "test-2026-09-01"
        assert body["current_index"] == 0  # reparti de zéro, pas de seek() hors bornes


class TestOptionsPreview:
    def test_preview_waits_without_a_candle_and_never_claims_order_evidence(self, replay_client, dataset_path):
        replay_client.post("/api/replay/session/reset")

        response = replay_client.get("/api/replay/options-preview")
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "SYNTHETIC_REPLAY_FIXTURE"
        assert body["strategy_type_code"] == "moving_average_crossover"
        assert body["signal"] == "HOLD"
        assert body["option_action"] == "NO_ORDER"
        assert body["option_instrument"] is None
        assert body["risk_status"] == "NOT_EVALUATED_IN_REPLAY"
        assert body["execution_status"] == "NOT_SENT_REPLAY"
        assert body["is_order_evidence"] is False

    def test_preview_uses_existing_ma_mapping_to_synthetic_long_call(self, replay_client, tmp_path, monkeypatch):
        path = tmp_path / "crossover-dataset.json"
        dataset = build_dataset(
            dataset_id="replay-preview-crossover",
            trading_day="2026-08-31",
            timezone="America/New_York",
            bars_by_symbol=_crossover_bars_by_symbol(),
        )
        save_dataset(dataset, path)
        monkeypatch.setattr(settings, "replay_dataset_path", str(path))

        replay_client.post("/api/replay/session/reset")
        for _ in range(22):
            replay_client.post("/api/replay/session/advance")

        with engine.connect() as conn:
            orders_before = conn.execute(
                text(
                    "SELECT COUNT(*) FROM orders WHERE execution_context_id = "
                    "(SELECT id FROM execution_contexts WHERE kind = 'REPLAY' AND is_active = true LIMIT 1)"
                )
            ).scalar_one()

        first = replay_client.get("/api/replay/options-preview")
        second = replay_client.get("/api/replay/options-preview")
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()  # no randomness, no external quote

        body = first.json()
        assert body["signal"] == "BUY"
        assert body["option_action"] == "LONG_CALL"
        assert body["option_instrument"]["option_type"] == "call"
        assert body["option_instrument"]["symbol"].startswith("AAPL260918C")
        assert body["option_instrument"]["quantity"] == 1
        assert body["is_order_evidence"] is False
        with engine.connect() as conn:
            orders_after = conn.execute(
                text(
                    "SELECT COUNT(*) FROM orders WHERE execution_context_id = "
                    "(SELECT id FROM execution_contexts WHERE kind = 'REPLAY' AND is_active = true LIMIT 1)"
                )
            ).scalar_one()
        assert orders_after == orders_before


class TestIsolationBetweenContexts:
    def test_replay_session_is_not_visible_from_paper_context(self, logged_in_client, dataset_path):
        replay_resp = logged_in_client.post("/api/contexts/select", json={"kind": "REPLAY"})
        assert replay_resp.status_code == 200
        logged_in_client.post("/api/replay/session/reset")
        logged_in_client.post("/api/replay/session/advance")

        # Bascule vers Paper (confirmation requise puisqu'un contexte était
        # déjà actif, §B06) — la route Replay doit refuser, pas essayer de
        # servir un état orphelin.
        switch_resp = logged_in_client.post(
            "/api/contexts/select", json={"kind": "PAPER", "confirm": True}
        )
        assert switch_resp.status_code == 200

        response = logged_in_client.get("/api/replay/session")
        assert response.status_code == 400
