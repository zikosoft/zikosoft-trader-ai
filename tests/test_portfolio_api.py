"""B18 — Portefeuille, positions et historique (`/api/portfolio/*`). Contre
PostgreSQL/Redis réels et l'app FastAPI réelle (TestClient), aucun mock —
insère directement des `portfolio_snapshots`/`positions_snapshots` (ce que
`workers/portfolio_worker/main.py` écrirait réellement, testé séparément
dans `test_portfolio_worker.py`) plutôt que de faire tourner le worker ici,
même principe que `test_strategy_instances_api.py` (B12) qui insère des
`strategy_runs` directement plutôt que de faire tourner le Strategy Agent."""

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
        conn.execute(text("DELETE FROM portfolio_snapshots"))
        conn.execute(text("DELETE FROM positions_snapshots"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM portfolio_snapshots"))
        conn.execute(text("DELETE FROM positions_snapshots"))
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


def _insert_portfolio_snapshot(
    *,
    user_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    cash: float = 50000.0,
    buying_power: float = 100000.0,
    portfolio_value: float = 150000.0,
    daily_pl: float | None = 250.0,
    total_pl: float | None = 5000.0,
    snapshot_at: datetime | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO portfolio_snapshots "
                "(id, user_id, execution_context_id, cash, buying_power, portfolio_value, "
                " daily_pl, total_pl, raw_provider_payload, snapshot_at) "
                "VALUES (:id, :user_id, :ctx_id, :cash, :buying_power, :portfolio_value, "
                " :daily_pl, :total_pl, '{}'::jsonb, :snapshot_at)"
            ),
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "ctx_id": execution_context_id,
                "cash": cash,
                "buying_power": buying_power,
                "portfolio_value": portfolio_value,
                "daily_pl": daily_pl,
                "total_pl": total_pl,
                "snapshot_at": snapshot_at or datetime.now(UTC),
            },
        )


def _insert_position_snapshot(
    *,
    user_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    symbol: str = "AAPL",
    quantity: float = 10.0,
    average_entry_price: float | None = 150.0,
    market_value: float | None = 1550.0,
    unrealized_pl: float | None = 50.0,
    snapshot_at: datetime | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO positions_snapshots "
                "(id, user_id, execution_context_id, symbol, quantity, average_entry_price, "
                " market_value, unrealized_pl, snapshot_at) "
                "VALUES (:id, :user_id, :ctx_id, :symbol, :quantity, :avg_price, "
                " :market_value, :unrealized_pl, :snapshot_at)"
            ),
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "ctx_id": execution_context_id,
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": average_entry_price,
                "market_value": market_value,
                "unrealized_pl": unrealized_pl,
                "snapshot_at": snapshot_at or datetime.now(UTC),
            },
        )


class TestAuthRequired:
    def test_summary_requires_auth(self, client):
        assert client.get("/api/portfolio/summary").status_code == 401

    def test_positions_requires_auth(self, client):
        assert client.get("/api/portfolio/positions").status_code == 401

    def test_history_requires_auth(self, client):
        assert client.get("/api/portfolio/history").status_code == 401

    def test_performance_requires_auth(self, client):
        assert client.get("/api/portfolio/performance").status_code == 401


class TestNoActiveContext:
    """§B18 — même principe que `strategy_instances.py` (B12) : aucun
    contexte actif est une erreur de validation (400), pas un 404/500."""

    def test_summary_without_active_context(self, logged_in_client):
        response = logged_in_client.get("/api/portfolio/summary")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_positions_without_active_context(self, logged_in_client):
        assert logged_in_client.get("/api/portfolio/positions").status_code == 400

    def test_history_without_active_context(self, logged_in_client):
        assert logged_in_client.get("/api/portfolio/history").status_code == 400

    def test_performance_without_active_context(self, logged_in_client):
        assert logged_in_client.get("/api/portfolio/performance").status_code == 400


class TestSummary:
    def test_no_snapshot_yet_returns_404_not_fabricated_zeroes(self, paper_client):
        """§B18 anti-fabrication — "pas encore de portefeuille" doit rester
        honnêtement absent, jamais un résumé à zéro qui prétendrait
        représenter un vrai compte."""
        response = paper_client.get("/api/portfolio/summary")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_latest_snapshot(self, paper_client, demo_user_id, paper_context_id):
        _insert_portfolio_snapshot(
            user_id=demo_user_id,
            execution_context_id=paper_context_id,
            snapshot_at=datetime.now(UTC) - timedelta(minutes=10),
            portfolio_value=140000.0,
        )
        _insert_portfolio_snapshot(
            user_id=demo_user_id, execution_context_id=paper_context_id, portfolio_value=150000.0
        )

        response = paper_client.get("/api/portfolio/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["portfolio_value"] == 150000.0
        assert body["cash"] == 50000.0
        assert body["buying_power"] == 100000.0
        assert body["daily_pl"] == 250.0
        assert body["total_pl"] == 5000.0

    def test_null_daily_and_total_pl_stay_null_not_zero(self, paper_client, demo_user_id, paper_context_id):
        """§B18 anti-fabrication — un premier snapshot sans référence
        antérieure a `daily_pl`/`total_pl` honnêtement absents (voir
        `workers/portfolio_worker`), jamais convertis en `0.0`."""
        _insert_portfolio_snapshot(
            user_id=demo_user_id, execution_context_id=paper_context_id, daily_pl=None, total_pl=None
        )
        response = paper_client.get("/api/portfolio/summary")
        assert response.status_code == 200
        assert response.json()["daily_pl"] is None
        assert response.json()["total_pl"] is None

    def test_isolated_by_execution_context(self, paper_client, logged_in_client, demo_user_id, paper_context_id):
        """§R06 — un snapshot REPLAY ne doit jamais apparaître alors que
        PAPER est actif."""
        with engine.connect() as conn:
            replay_ctx_id = conn.execute(
                text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
                {"uid": demo_user_id},
            ).scalar_one()
        _insert_portfolio_snapshot(user_id=demo_user_id, execution_context_id=replay_ctx_id, portfolio_value=999.0)

        response = paper_client.get("/api/portfolio/summary")
        assert response.status_code == 404  # rien pour PAPER, le snapshot REPLAY ne compte pas

    def test_response_is_cached_briefly(self, paper_client, demo_user_id, paper_context_id):
        """§B18 "cache court Redis" — une deuxième insertion après le
        premier appel ne doit PAS apparaître immédiatement (tant que le TTL
        n'a pas expiré) : preuve que la réponse vient bien du cache, pas
        d'une relecture DB à chaque appel."""
        _insert_portfolio_snapshot(user_id=demo_user_id, execution_context_id=paper_context_id, portfolio_value=1.0)
        first = paper_client.get("/api/portfolio/summary")
        assert first.json()["portfolio_value"] == 1.0

        _insert_portfolio_snapshot(user_id=demo_user_id, execution_context_id=paper_context_id, portfolio_value=2.0)
        second = paper_client.get("/api/portfolio/summary")
        assert second.json()["portfolio_value"] == 1.0  # servi depuis le cache, pas relu


class TestPositions:
    def test_no_positions_tour_yet_returns_empty_with_null_snapshot_at(self, paper_client):
        response = paper_client.get("/api/portfolio/positions")
        assert response.status_code == 200
        body = response.json()
        assert body["positions"] == []
        assert body["snapshot_at"] is None

    def test_returns_latest_tour_only(self, paper_client, demo_user_id, paper_context_id):
        """§B18 — `latest_positions()` s'ancre sur le `PortfolioSnapshot` le
        plus récent, pas sur `MAX(positions_snapshots.snapshot_at)` seul
        (voir docstring de `latest_positions`) : chaque tour insère donc
        AUSSI un `portfolio_snapshot` au même `snapshot_at`, comme le ferait
        réellement le worker."""
        older = datetime.now(UTC) - timedelta(minutes=10)
        latest = datetime.now(UTC)
        _insert_portfolio_snapshot(user_id=demo_user_id, execution_context_id=paper_context_id, snapshot_at=older)
        _insert_position_snapshot(
            user_id=demo_user_id, execution_context_id=paper_context_id, symbol="OLD", snapshot_at=older
        )
        _insert_portfolio_snapshot(user_id=demo_user_id, execution_context_id=paper_context_id, snapshot_at=latest)
        _insert_position_snapshot(
            user_id=demo_user_id, execution_context_id=paper_context_id, symbol="AAPL", snapshot_at=latest
        )
        _insert_position_snapshot(
            user_id=demo_user_id, execution_context_id=paper_context_id, symbol="MSFT", snapshot_at=latest
        )

        response = paper_client.get("/api/portfolio/positions")
        assert response.status_code == 200
        body = response.json()
        symbols = {p["symbol"] for p in body["positions"]}
        assert symbols == {"AAPL", "MSFT"}
        assert body["snapshot_at"] is not None

    def test_flat_account_tour_happened_but_zero_positions(self, paper_client, demo_user_id, paper_context_id):
        """§B18 — le cas que l'ancrage sur `PortfolioSnapshot` rend
        possible : un tour a eu lieu (portfolio_snapshot existe) mais 0
        position ouverte (aucune ligne positions_snapshots) — distinct de
        "le worker n'a jamais tourné" (`snapshot_at is None`)."""
        _insert_portfolio_snapshot(user_id=demo_user_id, execution_context_id=paper_context_id)
        response = paper_client.get("/api/portfolio/positions")
        assert response.status_code == 200
        body = response.json()
        assert body["positions"] == []
        assert body["snapshot_at"] is not None


class TestHistory:
    def test_paginates_and_orders_most_recent_first(self, paper_client, demo_user_id, paper_context_id):
        base = datetime.now(UTC)
        for i in range(5):
            _insert_portfolio_snapshot(
                user_id=demo_user_id,
                execution_context_id=paper_context_id,
                portfolio_value=100000.0 + i,
                snapshot_at=base - timedelta(hours=i),
            )

        response = paper_client.get("/api/portfolio/history", params={"limit": 2, "offset": 0})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert body["limit"] == 2
        assert len(body["items"]) == 2
        assert body["items"][0]["portfolio_value"] == 100000.0  # le plus récent (i=0) en premier

        page2 = paper_client.get("/api/portfolio/history", params={"limit": 2, "offset": 2})
        assert page2.json()["items"][0]["portfolio_value"] == 100002.0

    def test_excludes_snapshots_older_than_requested_days(self, paper_client, demo_user_id, paper_context_id):
        _insert_portfolio_snapshot(
            user_id=demo_user_id,
            execution_context_id=paper_context_id,
            portfolio_value=1.0,
            snapshot_at=datetime.now(UTC) - timedelta(days=95),
        )
        _insert_portfolio_snapshot(user_id=demo_user_id, execution_context_id=paper_context_id, portfolio_value=2.0)

        response = paper_client.get("/api/portfolio/history", params={"days": 90})
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["portfolio_value"] == 2.0

    def test_days_capped_at_90(self, paper_client):
        response = paper_client.get("/api/portfolio/history", params={"days": 365})
        assert response.status_code == 422  # §B18 "limité à 90 jours" — appliqué côté backend


class TestPerformanceCards:
    def test_no_history_all_cards_unavailable(self, paper_client):
        response = paper_client.get("/api/portfolio/performance")
        assert response.status_code == 200
        cards = response.json()["cards"]
        assert {c["window"] for c in cards} == {"1D", "3D", "7D"}
        assert all(c["available"] is False for c in cards)
        assert all(c["reason"] == "Not enough account history yet" for c in cards)
        assert all(c["value_change"] is None for c in cards)

    def test_enough_history_computes_value_and_percent_change(self, paper_client, demo_user_id, paper_context_id):
        now = datetime.now(UTC)
        _insert_portfolio_snapshot(
            user_id=demo_user_id,
            execution_context_id=paper_context_id,
            portfolio_value=100000.0,
            snapshot_at=now - timedelta(days=10),
        )
        _insert_portfolio_snapshot(
            user_id=demo_user_id, execution_context_id=paper_context_id, portfolio_value=110000.0, snapshot_at=now
        )

        response = paper_client.get("/api/portfolio/performance")
        cards = {c["window"]: c for c in response.json()["cards"]}
        for window in ("1D", "3D", "7D"):
            assert cards[window]["available"] is True
            assert cards[window]["value_change"] == 10000.0
            assert round(cards[window]["percent_change"], 2) == 10.0

    def test_partial_history_some_windows_unavailable(self, paper_client, demo_user_id, paper_context_id):
        """2 jours d'historique : la fenêtre 1D est calculable, pas 7D."""
        now = datetime.now(UTC)
        _insert_portfolio_snapshot(
            user_id=demo_user_id,
            execution_context_id=paper_context_id,
            portfolio_value=100000.0,
            snapshot_at=now - timedelta(days=2),
        )
        _insert_portfolio_snapshot(
            user_id=demo_user_id, execution_context_id=paper_context_id, portfolio_value=101000.0, snapshot_at=now
        )

        response = paper_client.get("/api/portfolio/performance")
        cards = {c["window"]: c for c in response.json()["cards"]}
        assert cards["1D"]["available"] is True
        assert cards["7D"]["available"] is False
        assert cards["7D"]["reason"] == "Not enough account history yet"
