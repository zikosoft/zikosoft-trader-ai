"""B26 — Ordres récents (`GET /api/orders/recent`). Contre PostgreSQL/Redis
réels et l'app FastAPI réelle (TestClient), aucun mock — insère directement
des `orders` (ce que l'Order Worker, B17, écrirait réellement, testé
séparément dans `test_order_worker.py`), même principe que
`test_portfolio_api.py` (B18)."""

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
        conn.execute(text("DELETE FROM order_events"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM order_events"))
        conn.execute(text("DELETE FROM orders"))
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


def _insert_order(
    *,
    user_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    symbol: str = "AAPL",
    side: str = "buy",
    status: str = "filled",
    quantity: float | None = 10.0,
    notional: float | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    order_id = uuid.uuid4()
    unique = uuid.uuid4().hex[:12]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO orders "
                "(id, user_id, execution_context_id, symbol, side, notional, quantity, order_type, "
                " time_in_force, status, idempotency_key, client_order_id, correlation_id, created_at, updated_at) "
                "VALUES (:id, :user_id, :ctx_id, :symbol, :side, :notional, :quantity, 'market', "
                " 'day', :status, :idem_key, :client_order_id, :correlation_id, :created_at, :created_at)"
            ),
            {
                "id": order_id,
                "user_id": user_id,
                "ctx_id": execution_context_id,
                "symbol": symbol,
                "side": side,
                "notional": notional,
                "quantity": quantity,
                "status": status,
                "idem_key": f"test-{unique}",
                "client_order_id": f"test-client-{unique}",
                "correlation_id": uuid.uuid4(),
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return order_id


class TestAuthRequired:
    def test_recent_requires_auth(self, client):
        assert client.get("/api/orders/recent").status_code == 401


class TestNoActiveContext:
    def test_recent_without_active_context(self, logged_in_client):
        response = logged_in_client.get("/api/orders/recent")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestRecentOrders:
    def test_no_orders_yet_returns_empty_list(self, paper_client):
        response = paper_client.get("/api/orders/recent")
        assert response.status_code == 200
        assert response.json()["orders"] == []

    def test_returns_most_recent_first(self, paper_client, demo_user_id, paper_context_id):
        now = datetime.now(UTC)
        _insert_order(
            user_id=demo_user_id, execution_context_id=paper_context_id, symbol="OLD", created_at=now - timedelta(minutes=10)
        )
        _insert_order(user_id=demo_user_id, execution_context_id=paper_context_id, symbol="NEW", created_at=now)

        response = paper_client.get("/api/orders/recent")
        assert response.status_code == 200
        orders = response.json()["orders"]
        assert [o["symbol"] for o in orders] == ["NEW", "OLD"]

    def test_limit_is_respected_and_capped(self, paper_client, demo_user_id, paper_context_id):
        for i in range(5):
            _insert_order(user_id=demo_user_id, execution_context_id=paper_context_id, symbol=f"SYM{i}")

        response = paper_client.get("/api/orders/recent", params={"limit": 2})
        assert response.status_code == 200
        assert len(response.json()["orders"]) == 2

        too_high = paper_client.get("/api/orders/recent", params={"limit": 999})
        assert too_high.status_code == 422  # borné par MAX_RECENT_LIMIT

    def test_isolated_by_execution_context(self, paper_client, logged_in_client, demo_user_id, paper_context_id):
        """§R06 — un ordre REPLAY ne doit jamais apparaître alors que PAPER
        est actif."""
        with engine.connect() as conn:
            replay_ctx_id = conn.execute(
                text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
                {"uid": demo_user_id},
            ).scalar_one()
        _insert_order(user_id=demo_user_id, execution_context_id=replay_ctx_id, symbol="REPLAYONLY")

        response = paper_client.get("/api/orders/recent")
        assert response.json()["orders"] == []

    def test_order_fields_are_real_not_fabricated(self, paper_client, demo_user_id, paper_context_id):
        _insert_order(
            user_id=demo_user_id,
            execution_context_id=paper_context_id,
            symbol="AAPL",
            side="buy",
            status="filled",
            quantity=10.0,
            notional=None,
        )
        response = paper_client.get("/api/orders/recent")
        order = response.json()["orders"][0]
        assert order["symbol"] == "AAPL"
        assert order["side"] == "buy"
        assert order["status"] == "filled"
        assert order["quantity"] == 10.0
        assert order["notional"] is None
