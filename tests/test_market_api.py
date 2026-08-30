"""B27 — Graphiques marché et analytics (`GET /api/market/*`). Contre
PostgreSQL/Redis réels et l'app FastAPI réelle (TestClient), aucun mock —
insère directement `market_bars`/`market_quotes` (ce que
`agents/market_agent/main.py::tick()` écrirait réellement, testé
séparément dans `test_market_agent.py`), `orders`/`order_events`
(§B17/`test_order_worker.py`), `agent_decisions`/`risk_decisions`
(§B13-B15/`test_agent_activity_api.py`) et `strategies`/`strategy_definitions`
(§B11-B12/`test_order_worker.py::_make_strategy`), même principe que
`test_orders_api.py`/`test_agent_activity_api.py` (B26)."""

from __future__ import annotations

import json
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
        conn.execute(text("DELETE FROM market_bars"))
        conn.execute(text("DELETE FROM market_quotes"))
        conn.execute(text("DELETE FROM order_events"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code LIKE 'market_api_test_%'"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM market_bars"))
        conn.execute(text("DELETE FROM market_quotes"))
        conn.execute(text("DELETE FROM order_events"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code LIKE 'market_api_test_%'"))
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


def _insert_bar(*, symbol: str, timeframe: str = "1Day", bar_at: datetime, close: float, volume: float | None = 100.0) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO market_bars (id, symbol, timeframe, bar_at, open, high, low, close, volume) "
                "VALUES (:id, :symbol, :timeframe, :bar_at, :close, :close, :close, :close, :volume)"
            ),
            {"id": uuid.uuid4(), "symbol": symbol, "timeframe": timeframe, "bar_at": bar_at, "close": close, "volume": volume},
        )


def _insert_quote(*, symbol: str, price: float, as_of: datetime | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO market_quotes (symbol, price, as_of, raw) "
                "VALUES (:symbol, :price, :as_of, '{}'::jsonb)"
            ),
            {"symbol": symbol, "price": price, "as_of": as_of},
        )


def _insert_order(
    *,
    user_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    symbol: str = "AAPL",
    side: str = "buy",
    status: str = "filled",
    quantity: float | None = 10.0,
    stop_loss: dict | None = None,
    take_profit: dict | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    order_id = uuid.uuid4()
    unique = uuid.uuid4().hex[:12]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO orders "
                "(id, user_id, execution_context_id, symbol, side, quantity, order_type, time_in_force, "
                " status, stop_loss, take_profit, idempotency_key, client_order_id, correlation_id, "
                " filled_at, submitted_at, created_at, updated_at) "
                "VALUES (:id, :user_id, :ctx_id, :symbol, :side, :quantity, 'market', 'day', "
                " :status, CAST(:stop_loss AS jsonb), CAST(:take_profit AS jsonb), :idem_key, :client_order_id, "
                " :correlation_id, :filled_at, :submitted_at, :created_at, :created_at)"
            ),
            {
                "id": order_id,
                "user_id": user_id,
                "ctx_id": execution_context_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "status": status,
                "stop_loss": json.dumps(stop_loss) if stop_loss is not None else None,
                "take_profit": json.dumps(take_profit) if take_profit is not None else None,
                "idem_key": f"test-{unique}",
                "client_order_id": f"test-client-{unique}",
                "correlation_id": uuid.uuid4(),
                "filled_at": created_at or (datetime.now(UTC) if status == "filled" else None),
                "submitted_at": created_at or datetime.now(UTC),
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return order_id


def _insert_order_event(*, order_id: uuid.UUID, execution_context_id: uuid.UUID, event_type: str, payload: dict, occurred_at: datetime | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO order_events (id, execution_context_id, order_id, event_type, payload, occurred_at) "
                "VALUES (:id, :ctx_id, :order_id, :event_type, CAST(:payload AS jsonb), :occurred_at)"
            ),
            {
                "id": uuid.uuid4(),
                "ctx_id": execution_context_id,
                "order_id": order_id,
                "event_type": event_type,
                "payload": json.dumps(payload),
                "occurred_at": occurred_at or datetime.now(UTC),
            },
        )


def _insert_agent_decision(
    *,
    execution_context_id: uuid.UUID,
    symbol: str = "AAPL",
    strategy_id: uuid.UUID | None = None,
    decision_type: str = "PROPOSAL",
    outcome: str = "BUY",
    confidence: int | None = 7500,
    text_reasoning: str = "moving average crossover",
    created_at: datetime | None = None,
) -> uuid.UUID:
    decision_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_decisions "
                "(id, execution_context_id, strategy_id, agent_type, decision_type, outcome, confidence, "
                " reasoning, risk_flags, market_data_timestamp, correlation_id, created_at, updated_at) "
                "VALUES (:id, :ctx_id, :strategy_id, 'strategy_agent', :decision_type, :outcome, :confidence, "
                " CAST(:reasoning AS jsonb), '[]'::jsonb, :market_data_timestamp, :correlation_id, :created_at, :created_at)"
            ),
            {
                "id": decision_id,
                "ctx_id": execution_context_id,
                "strategy_id": strategy_id,
                "decision_type": decision_type,
                "outcome": outcome,
                "confidence": confidence,
                "reasoning": json.dumps({"text": text_reasoning, "symbol": symbol}),
                "market_data_timestamp": (created_at or datetime.now(UTC)).isoformat(),
                "correlation_id": uuid.uuid4(),
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return decision_id


def _insert_risk_decision(
    *, execution_context_id: uuid.UUID, agent_decision_id: uuid.UUID, outcome: str = "REJECTED", reasons: list | None = None, created_at: datetime | None = None
) -> uuid.UUID:
    risk_decision_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO risk_decisions "
                "(id, execution_context_id, agent_decision_id, outcome, reasons, adjustments, correlation_id, "
                " created_at, updated_at) "
                "VALUES (:id, :ctx_id, :agent_decision_id, :outcome, CAST(:reasons AS jsonb), '{}'::jsonb, "
                " :correlation_id, :created_at, :created_at)"
            ),
            {
                "id": risk_decision_id,
                "ctx_id": execution_context_id,
                "agent_decision_id": agent_decision_id,
                "outcome": outcome,
                "reasons": json.dumps(reasons or ["daily_loss_limit_exceeded"]),
                "correlation_id": uuid.uuid4(),
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return risk_decision_id


def _make_strategy(*, user_id: uuid.UUID, execution_context_id: uuid.UUID, name: str = "Test Strategy") -> uuid.UUID:
    type_code = f"market_api_test_{uuid.uuid4().hex[:8]}"
    def_id, strat_id = (uuid.uuid4() for _ in range(2))
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO strategy_definitions "
                "(id, type_code, version, manifest, parameter_schema, ui_schema, "
                " defaults_by_profile, required_market_data, is_active) "
                "VALUES (:id, :type_code, '1.0.0', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
                " '{}'::jsonb, '{}'::jsonb, true)"
            ),
            {"id": def_id, "type_code": type_code},
        )
        conn.execute(
            text(
                "INSERT INTO strategies "
                "(id, user_id, execution_context_id, strategy_definition_id, name, "
                " definition_version, parameters, symbols, risk_configuration, status) "
                "VALUES (:id, :user_id, :ctx_id, :def_id, :name, '1.0.0', "
                " '{}'::jsonb, CAST(:symbols AS jsonb), '{}'::jsonb, 'ACTIVE')"
            ),
            {"id": strat_id, "user_id": user_id, "ctx_id": execution_context_id, "def_id": def_id, "name": name, "symbols": json.dumps(["AAPL"])},
        )
    return strat_id


class TestAuthRequired:
    @pytest.mark.parametrize(
        "path",
        ["/api/market/symbols", "/api/market/bars?symbol=AAPL", "/api/market/quote?symbol=AAPL",
         "/api/market/orders?symbol=AAPL", "/api/market/decisions?symbol=AAPL", "/api/market/strategy-activity"],
    )
    def test_requires_auth(self, client, path):
        assert client.get(path).status_code == 401


class TestNoActiveContext:
    @pytest.mark.parametrize("path", ["/api/market/orders?symbol=AAPL", "/api/market/decisions?symbol=AAPL", "/api/market/strategy-activity"])
    def test_context_scoped_routes_require_active_context(self, logged_in_client, path):
        response = logged_in_client.get(path)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("path", ["/api/market/symbols", "/api/market/bars?symbol=AAPL", "/api/market/quote?symbol=ZTESTNONE"])
    def test_global_market_routes_do_not_require_active_context(self, logged_in_client, path):
        # §B27 — donnée de marché, pas propriété d'un contexte d'exécution
        # (voir backend/app/models/market_data.py) : ne doit jamais exiger
        # de contexte actif, contrairement aux routes scopées ci-dessus.
        response = logged_in_client.get(path)
        assert response.status_code != 400


class TestSymbols:
    def test_no_bars_yet_returns_empty_list_never_a_fake_watchlist(self, paper_client):
        # §B27 — jamais `market_agent.DEMO_WATCHLIST` tel quel, voir
        # `backend/app/market.py::list_symbols`.
        response = paper_client.get("/api/market/symbols")
        assert response.status_code == 200
        assert response.json()["symbols"] == []

    def test_returns_distinct_symbols_with_at_least_one_bar(self, paper_client):
        now = datetime.now(UTC)
        _insert_bar(symbol="AAPL", bar_at=now, close=190.0)
        _insert_bar(symbol="AAPL", bar_at=now - timedelta(days=1), close=188.0)
        _insert_bar(symbol="MSFT", bar_at=now, close=420.0)

        response = paper_client.get("/api/market/symbols")
        assert response.json()["symbols"] == ["AAPL", "MSFT"]


class TestBars:
    def test_no_bars_returns_empty_list(self, paper_client):
        response = paper_client.get("/api/market/bars", params={"symbol": "AAPL"})
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["bars"] == []

    def test_returns_ascending_chronological_order(self, paper_client):
        now = datetime.now(UTC)
        _insert_bar(symbol="AAPL", bar_at=now - timedelta(days=2), close=1.0)
        _insert_bar(symbol="AAPL", bar_at=now, close=3.0)
        _insert_bar(symbol="AAPL", bar_at=now - timedelta(days=1), close=2.0)

        response = paper_client.get("/api/market/bars", params={"symbol": "aapl"})  # lower-case volontaire
        closes = [b["close"] for b in response.json()["bars"]]
        assert closes == [1.0, 2.0, 3.0]  # le plus ancien en premier

    def test_limit_selects_most_recent_bars(self, paper_client):
        now = datetime.now(UTC)
        for i in range(5):
            _insert_bar(symbol="AAPL", bar_at=now - timedelta(days=4 - i), close=float(i))

        response = paper_client.get("/api/market/bars", params={"symbol": "AAPL", "limit": 2})
        closes = [b["close"] for b in response.json()["bars"]]
        assert closes == [3.0, 4.0]  # les 2 plus récentes, triées ascendant

    def test_filtered_by_timeframe(self, paper_client):
        now = datetime.now(UTC)
        _insert_bar(symbol="AAPL", timeframe="1Day", bar_at=now, close=100.0)
        _insert_bar(symbol="AAPL", timeframe="1Min", bar_at=now, close=99.0)

        response = paper_client.get("/api/market/bars", params={"symbol": "AAPL", "timeframe": "1Min"})
        closes = [b["close"] for b in response.json()["bars"]]
        assert closes == [99.0]

    def test_excessive_limit_is_rejected(self, paper_client):
        response = paper_client.get("/api/market/bars", params={"symbol": "AAPL", "limit": 99999})
        assert response.status_code == 422


class TestQuote:
    def test_no_quote_yet_returns_404_never_fabricated(self, paper_client):
        response = paper_client.get("/api/market/quote", params={"symbol": "ZTESTNONE"})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_returns_latest_quote(self, paper_client):
        _insert_quote(symbol="AAPL", price=191.5, as_of=datetime.now(UTC))
        response = paper_client.get("/api/market/quote", params={"symbol": "aapl"})
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["price"] == 191.5


class TestOrderMarkers:
    def test_no_orders_returns_empty_list(self, paper_client):
        response = paper_client.get("/api/market/orders", params={"symbol": "AAPL"})
        assert response.status_code == 200
        assert response.json()["orders"] == []

    def test_includes_stop_loss_take_profit_from_order_row(self, paper_client, demo_user_id, paper_context_id):
        # §B27 — forme réelle écrite par `workers/order_worker/main.py`
        # (`_build_bracket_legs`) : `{"stop_loss_pct": ..., "leg": {"stop_price": ...}}`.
        _insert_order(
            user_id=demo_user_id,
            execution_context_id=paper_context_id,
            symbol="AAPL",
            stop_loss={"stop_loss_pct": 2.0, "leg": {"stop_price": 180.0}},
            take_profit={"take_profit_pct": 4.0, "leg": {"limit_price": 210.0}},
        )
        response = paper_client.get("/api/market/orders", params={"symbol": "AAPL"})
        marker = response.json()["orders"][0]
        assert marker["stop_loss"] == {"stop_loss_pct": 2.0, "leg": {"stop_price": 180.0}}
        assert marker["take_profit"] == {"take_profit_pct": 4.0, "leg": {"limit_price": 210.0}}

    def test_extracts_filled_price_from_order_event_payload(self, paper_client, demo_user_id, paper_context_id):
        order_id = _insert_order(user_id=demo_user_id, execution_context_id=paper_context_id, symbol="AAPL", status="filled")
        _insert_order_event(
            order_id=order_id,
            execution_context_id=paper_context_id,
            event_type="order.filled",
            payload={"status": "filled", "filled_avg_price": "192.34"},
        )
        response = paper_client.get("/api/market/orders", params={"symbol": "AAPL"})
        marker = response.json()["orders"][0]
        assert marker["filled_price"] == 192.34

    def test_extracts_filled_price_from_nested_trade_update_payload(self, paper_client, demo_user_id, paper_context_id):
        order_id = _insert_order(user_id=demo_user_id, execution_context_id=paper_context_id, symbol="AAPL", status="filled")
        _insert_order_event(
            order_id=order_id,
            execution_context_id=paper_context_id,
            event_type="order.fill",
            payload={"event": "fill", "order": {"filled_avg_price": "88.10"}},
        )
        response = paper_client.get("/api/market/orders", params={"symbol": "AAPL"})
        assert response.json()["orders"][0]["filled_price"] == 88.10

    def test_no_extractable_price_is_none_never_fabricated(self, paper_client, demo_user_id, paper_context_id):
        order_id = _insert_order(user_id=demo_user_id, execution_context_id=paper_context_id, symbol="AAPL", status="pending")
        _insert_order_event(
            order_id=order_id, execution_context_id=paper_context_id, event_type="order.pending_new", payload={"status": "pending_new"}
        )
        response = paper_client.get("/api/market/orders", params={"symbol": "AAPL"})
        assert response.json()["orders"][0]["filled_price"] is None

    def test_filtered_by_symbol(self, paper_client, demo_user_id, paper_context_id):
        _insert_order(user_id=demo_user_id, execution_context_id=paper_context_id, symbol="AAPL")
        _insert_order(user_id=demo_user_id, execution_context_id=paper_context_id, symbol="MSFT")

        response = paper_client.get("/api/market/orders", params={"symbol": "MSFT"})
        orders = response.json()["orders"]
        assert len(orders) == 1

    def test_isolated_by_execution_context(self, paper_client, demo_user_id, paper_context_id):
        with engine.connect() as conn:
            replay_ctx_id = conn.execute(
                text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
                {"uid": demo_user_id},
            ).scalar_one()
        _insert_order(user_id=demo_user_id, execution_context_id=replay_ctx_id, symbol="AAPL")

        response = paper_client.get("/api/market/orders", params={"symbol": "AAPL"})
        assert response.json()["orders"] == []


class TestDecisionMarkers:
    def test_no_decisions_returns_empty_lists(self, paper_client):
        response = paper_client.get("/api/market/decisions", params={"symbol": "AAPL"})
        assert response.status_code == 200
        body = response.json()
        assert body["proposals"] == []
        assert body["risk_events"] == []

    def test_proposal_filtered_by_symbol_embedded_in_reasoning(self, paper_client, paper_context_id):
        _insert_agent_decision(execution_context_id=paper_context_id, symbol="AAPL", outcome="BUY")
        _insert_agent_decision(execution_context_id=paper_context_id, symbol="MSFT", outcome="SELL")

        response = paper_client.get("/api/market/decisions", params={"symbol": "AAPL"})
        proposals = response.json()["proposals"]
        assert len(proposals) == 1
        assert proposals[0]["outcome"] == "BUY"

    def test_risk_event_joined_via_agent_decision_symbol(self, paper_client, paper_context_id):
        decision_id = _insert_agent_decision(execution_context_id=paper_context_id, symbol="AAPL")
        _insert_risk_decision(execution_context_id=paper_context_id, agent_decision_id=decision_id, outcome="REJECTED")

        other_decision_id = _insert_agent_decision(execution_context_id=paper_context_id, symbol="MSFT")
        _insert_risk_decision(execution_context_id=paper_context_id, agent_decision_id=other_decision_id, outcome="REJECTED")

        response = paper_client.get("/api/market/decisions", params={"symbol": "AAPL"})
        risk_events = response.json()["risk_events"]
        assert len(risk_events) == 1
        assert risk_events[0]["outcome"] == "REJECTED"

    def test_isolated_by_execution_context(self, paper_client, demo_user_id, paper_context_id):
        with engine.connect() as conn:
            replay_ctx_id = conn.execute(
                text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
                {"uid": demo_user_id},
            ).scalar_one()
        _insert_agent_decision(execution_context_id=replay_ctx_id, symbol="AAPL")

        response = paper_client.get("/api/market/decisions", params={"symbol": "AAPL"})
        assert response.json()["proposals"] == []


class TestStrategyActivity:
    def test_no_strategies_returns_empty_list(self, paper_client):
        response = paper_client.get("/api/market/strategy-activity")
        assert response.status_code == 200
        assert response.json()["strategies"] == []

    def test_aggregates_order_count_and_notional_per_strategy_real_proxy_not_pnl(self, paper_client, demo_user_id, paper_context_id):
        strategy_id = _make_strategy(user_id=demo_user_id, execution_context_id=paper_context_id, name="MA Crossover")
        with engine.begin() as conn:
            for side, notional in (("buy", 100.0), ("buy", 50.0), ("sell", 40.0)):
                order_id = uuid.uuid4()
                unique = uuid.uuid4().hex[:12]
                conn.execute(
                    text(
                        "INSERT INTO orders "
                        "(id, user_id, execution_context_id, strategy_id, symbol, side, notional, order_type, "
                        " time_in_force, status, idempotency_key, client_order_id, correlation_id) "
                        "VALUES (:id, :user_id, :ctx_id, :strategy_id, 'AAPL', :side, :notional, 'market', 'day', "
                        " 'filled', :idem_key, :client_order_id, :correlation_id)"
                    ),
                    {
                        "id": order_id, "user_id": demo_user_id, "ctx_id": paper_context_id, "strategy_id": strategy_id,
                        "side": side, "notional": notional, "idem_key": f"test-{unique}", "client_order_id": f"test-client-{unique}",
                        "correlation_id": uuid.uuid4(),
                    },
                )

        response = paper_client.get("/api/market/strategy-activity")
        strategies = response.json()["strategies"]
        assert len(strategies) == 1
        entry = strategies[0]
        assert entry["name"] == "MA Crossover"
        assert entry["order_count"] == 3
        assert entry["buy_count"] == 2
        assert entry["sell_count"] == 1
        assert entry["total_notional"] == pytest.approx(190.0)

    def test_strategy_with_no_orders_yet_shows_zero_never_fabricated(self, paper_client, demo_user_id, paper_context_id):
        _make_strategy(user_id=demo_user_id, execution_context_id=paper_context_id, name="Fresh Strategy")
        response = paper_client.get("/api/market/strategy-activity")
        entry = response.json()["strategies"][0]
        assert entry["order_count"] == 0
        assert entry["total_notional"] == 0.0
