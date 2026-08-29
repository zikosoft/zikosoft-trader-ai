"""B17 — workers/order_worker/main.py. Intégration réelle contre
PostgreSQL/Redis (aucun mock d'infra interne) — seule la frontière HTTP
avec Alpaca est mockée (`respx`), même discipline que `test_onboarding.py`
(B07) pour `backend/app/alpaca_client.py`.

**Le chemin "prêt à placer" (sizing_pending=False) est construit
directement dans les tests** — jamais produit par le vrai B16 tant que
`sizing_pending` y reste toujours `true` (aucune logique de dimensionnement
d'ordre n'existe encore). Voir docstring de `workers/order_worker/main.py`
: "Aucun ordre live possible" (test P0) est au contraire exercé avec la
forme RÉELLE du payload publié par B16 aujourd'hui — c'est le comportement
permanent de cette V1, pas un cas limite.

Nécessite `.venv-agents` (le SDK `mcp` n'est installé que là, même raison
que `test_market_agent.py`) — skip proprement sous `.venv` backend."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

pytest.importorskip("mcp", reason="suite agents — lancer avec `make test-agents` (.venv-agents)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

os.environ.setdefault("APP_ENCRYPTION_KEY", "RB-l2-7BeTsBNRSaUSuU85CsRr1C18vHkEI3kMq7JiE=")

import order_worker.main as order_worker  # noqa: E402
from common.encryption import encrypt_secret  # noqa: E402
from sqlalchemy import text  # noqa: E402

from shared.events import EventEnvelope, Streams  # noqa: E402
from shared.risk_governance import set_trading_kill_switch_engaged  # noqa: E402

ALPACA_ORDERS_URL = "https://paper-api.alpaca.markets/v2/orders"


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture()
def engine():
    from app.db import engine as _engine  # noqa: PLC0415 — après importorskip/sys.path, volontaire

    return _engine


@pytest.fixture(autouse=True)
def _clean_state(engine, redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM order_events"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code LIKE 'order_worker_test_%'"))
        conn.execute(text("DELETE FROM user_trading_accounts WHERE metadata_json->>'test' = 'order_worker'"))
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'order-worker-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'order-worker-test-%'"))
        conn.commit()
    redis_client.delete(Streams.ORDER_COMMANDS, Streams.ORDER_EVENTS)
    redis_client.delete(f"{Streams.ORDER_COMMANDS}.dead-letter")
    set_trading_kill_switch_engaged(redis_client, False)
    yield
    order_worker._listeners.clear()
    order_worker._listeners_credentials.clear()
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM order_events"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code LIKE 'order_worker_test_%'"))
        conn.execute(text("DELETE FROM user_trading_accounts WHERE metadata_json->>'test' = 'order_worker'"))
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'order-worker-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'order-worker-test-%'"))
        conn.commit()


def _make_context(engine, *, kind="PAPER") -> dict:
    user_id = uuid.uuid4()
    ctx_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, 'x', 'Order Worker Test', true)"
            ),
            {"id": user_id, "email": f"order-worker-test-{user_id}@zikosofttrader.local"},
        )
        conn.execute(
            text(
                "INSERT INTO execution_contexts (id, user_id, kind, label, is_active) "
                "VALUES (:id, :user_id, :kind, 'order-worker-test', false)"
            ),
            {"id": ctx_id, "user_id": user_id, "kind": kind},
        )
    return {"user_id": user_id, "execution_context_id": ctx_id}


def _make_connected_account(engine, *, user_id) -> uuid.UUID:
    account_id = uuid.uuid4()
    provider_id = None
    with engine.connect() as conn:
        provider_id = conn.execute(text("SELECT id FROM trading_providers WHERE code = 'alpaca'")).scalar_one()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO user_trading_accounts "
                "(id, user_id, trading_provider_id, environment, status, "
                " encrypted_api_key, encrypted_secret_key, encryption_key_version, is_default, metadata_json) "
                "VALUES (:id, :user_id, :provider_id, 'paper', 'connected', "
                " :enc_api_key, :enc_secret_key, 1, true, CAST(:metadata AS jsonb))"
            ),
            {
                "id": account_id,
                "user_id": user_id,
                "provider_id": provider_id,
                "enc_api_key": encrypt_secret("SPIKE-FAKE-KEY-NOT-REAL"),
                "enc_secret_key": encrypt_secret("SPIKE-FAKE-SECRET-NOT-REAL"),
                "metadata": json.dumps({"test": "order_worker"}),
            },
        )
    return account_id


def _make_strategy(engine, *, user_id, execution_context_id, parameters=None) -> uuid.UUID:
    type_code = f"order_worker_test_{uuid.uuid4().hex[:8]}"
    parameters = {"stop_loss_pct": 2.0, "take_profit_pct": 4.0} if parameters is None else parameters
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
                "VALUES (:id, :user_id, :ctx_id, :def_id, 'Order Worker Test Strategy', '1.0.0', "
                " CAST(:parameters AS jsonb), CAST(:symbols AS jsonb), '{}'::jsonb, 'ACTIVE')"
            ),
            {
                "id": strat_id,
                "user_id": user_id,
                "ctx_id": execution_context_id,
                "def_id": def_id,
                "parameters": json.dumps(parameters),
                "symbols": json.dumps(["AAPL"]),
            },
        )
    return strat_id


def _make_risk_decision(engine, *, execution_context_id, strategy_id, outcome="APPROVED") -> uuid.UUID:
    agent_decision_id = uuid.uuid4()
    risk_decision_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_decisions "
                "(id, execution_context_id, strategy_id, agent_type, decision_type, outcome, confidence, "
                " reasoning, risk_flags, market_data_timestamp, correlation_id) "
                "VALUES (:id, :execution_context_id, :strategy_id, 'risk_critic_agent', 'CRITIQUE', 'APPROVE', "
                " 8000, '{}'::jsonb, '[]'::jsonb, :market_data_timestamp, :correlation_id)"
            ),
            {
                "id": agent_decision_id,
                "execution_context_id": execution_context_id,
                "strategy_id": strategy_id,
                "market_data_timestamp": datetime.now(UTC).isoformat(),
                "correlation_id": uuid.uuid4(),
            },
        )
        conn.execute(
            text(
                "INSERT INTO risk_decisions "
                "(id, execution_context_id, agent_decision_id, outcome, reasons, adjustments, correlation_id) "
                "VALUES (:id, :execution_context_id, :agent_decision_id, :outcome, '[]'::jsonb, '{}'::jsonb, :correlation_id)"
            ),
            {
                "id": risk_decision_id,
                "execution_context_id": execution_context_id,
                "agent_decision_id": agent_decision_id,
                "outcome": outcome,
                "correlation_id": uuid.uuid4(),
            },
        )
    return risk_decision_id


def _command_envelope(*, execution_context_id, user_id, risk_decision_id, strategy_id, **payload_overrides) -> EventEnvelope:
    payload = {
        "strategy_id": str(strategy_id),
        "risk_decision_id": str(risk_decision_id),
        "agent_decision_id": str(uuid.uuid4()),
        "explanation_agent_decision_id": str(uuid.uuid4()),
        "symbol": "AAPL",
        "side": "buy",
        "order_type": "market",
        "time_in_force": "day",
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "reference_price": 150.0,
        "notional": None,
        "quantity": None,
        "sizing_pending": True,
        "adjustments": {},
    }
    payload.update(payload_overrides)
    return EventEnvelope(
        event_type="order.command.prepared",
        correlation_id=uuid.uuid4(),
        execution_context_id=uuid.UUID(str(execution_context_id)),
        user_id=uuid.UUID(str(user_id)),
        payload=payload,
    )


def _fetch_order(engine, *, client_order_id) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM orders WHERE client_order_id = :cid"), {"cid": client_order_id}).mappings().first()
    return dict(row) if row is not None else None


def _fetch_order_events(engine, *, order_id) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM order_events WHERE order_id = :order_id ORDER BY occurred_at"), {"order_id": order_id}
        ).mappings().all()
    return [dict(r) for r in rows]


def _drain(redis_client, stream: str) -> list[dict]:
    entries = redis_client.xrange(stream, min="-", max="+")
    out = []
    for _mid, fields in entries:
        raw = fields.get(b"envelope") or fields.get("envelope")
        if isinstance(raw, bytes):
            raw = raw.decode()
        out.append(json.loads(raw))
    return out


def _alpaca_order_response(*, client_order_id: str, status: str = "accepted", order_id: str | None = None) -> dict:
    return {
        "id": order_id or str(uuid.uuid4()),
        "client_order_id": client_order_id,
        "status": status,
        "symbol": "AAPL",
        "side": "buy",
        "submitted_at": datetime.now(UTC).isoformat(),
    }


# ----------------------------------------------------------------------
# Contrat / anomalies — avant tout appel Alpaca.
# ----------------------------------------------------------------------


class TestContractAndAnomalies:
    def test_invalid_contract_dead_letters(self, engine, redis_client):
        ctx = _make_context(engine)
        envelope = EventEnvelope(
            event_type="order.command.prepared",
            correlation_id=uuid.uuid4(),
            execution_context_id=ctx["execution_context_id"],
            user_id=ctx["user_id"],
            payload={"symbol": "AAPL"},  # champs requis manquants — invalide
        )

        order_worker._process_envelope(engine, redis_client, envelope)

        dead = _drain(redis_client, Streams.dead_letter(Streams.ORDER_COMMANDS))
        assert len(dead) == 1
        assert dead[0]["event_type"] == "order.command.invalid"
        assert "contrat OrderCommand invalide" in dead[0]["payload"]["reason"]
        assert _fetch_order(engine, client_order_id="zst-nonexistent") is None

    def test_risk_decision_not_approved_is_treated_as_anomaly(self, engine, redis_client):
        ctx = _make_context(engine)
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(
            engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id, outcome="REJECTED"
        )
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id
        )

        order_worker._process_envelope(engine, redis_client, envelope)

        assert _fetch_order(engine, client_order_id=f"zst-{risk_decision_id}") is None
        assert _drain(redis_client, Streams.ORDER_EVENTS) == []


# ----------------------------------------------------------------------
# Chemins bloqués avant tout appel Alpaca.
# ----------------------------------------------------------------------


class TestBlockedPaths:
    def test_replay_context_defers_without_alpaca_call(self, engine, redis_client):
        ctx = _make_context(engine, kind="REPLAY")
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            sizing_pending=False, notional=1000.0,
        )

        with respx.mock(assert_all_called=False) as mock:
            order_worker._process_envelope(engine, redis_client, envelope)
        assert not mock.calls

        order = _fetch_order(engine, client_order_id=f"zst-{risk_decision_id}")
        assert order is not None
        assert order["status"] == "deferred_replay"
        events = _drain(redis_client, Streams.ORDER_EVENTS)
        assert len(events) == 1
        assert events[0]["payload"]["status"] == "deferred_replay"

    def test_paper_without_connected_account_blocks(self, engine, redis_client):
        ctx = _make_context(engine, kind="PAPER")
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            sizing_pending=False, notional=1000.0,
        )

        order_worker._process_envelope(engine, redis_client, envelope)

        order = _fetch_order(engine, client_order_id=f"zst-{risk_decision_id}")
        assert order["status"] == "blocked_no_trading_account"

    def test_sizing_pending_blocks_aucun_ordre_live_possible(self, engine, redis_client):
        """§test P0 "Aucun ordre live possible" — forme RÉELLE du payload
        publié par B16 aujourd'hui (`sizing_pending=true`, `notional`/
        `quantity` toujours `None`) : comportement permanent de cette V1,
        pas un cas limite construit artificiellement."""
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id
        )  # sizing_pending=True par défaut, comme B16 le publie toujours

        with respx.mock(assert_all_called=False) as mock:
            order_worker._process_envelope(engine, redis_client, envelope)
        assert not mock.calls, "aucun appel Alpaca ne doit jamais partir tant que sizing_pending=true"

        order = _fetch_order(engine, client_order_id=f"zst-{risk_decision_id}")
        assert order["status"] == "blocked_sizing_pending"

    def test_kill_switch_engaged_blocks_before_alpaca_call(self, engine, redis_client):
        """§B31 "Bloquer Order Worker" — vérifié en premier, avant même le
        contexte d'exécution : une commande par ailleurs entièrement prête
        (sizing_pending=False, compte connecté) n'atteint jamais Alpaca tant
        que le kill switch reste engagé."""
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(
            engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"],
            parameters={"stop_loss_pct": 2.0, "take_profit_pct": 4.0},
        )
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            side="buy", reference_price=150.0, stop_loss_pct=2.0, take_profit_pct=4.0,
            sizing_pending=False, notional=1000.0,
        )
        set_trading_kill_switch_engaged(redis_client, True)

        with respx.mock(assert_all_called=False) as mock:
            order_worker._process_envelope(engine, redis_client, envelope)
        assert not mock.calls, "aucun appel Alpaca ne doit jamais partir tant que le kill switch est engagé"

        order = _fetch_order(engine, client_order_id=f"zst-{risk_decision_id}")
        assert order["status"] == "blocked_kill_switch"


# ----------------------------------------------------------------------
# Chemin "prêt à placer" — construit directement (voir docstring module).
# ----------------------------------------------------------------------


class TestReadyToPlace:
    def test_order_accepted_records_bracket_and_request_id(self, engine, redis_client):
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(
            engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"],
            parameters={"stop_loss_pct": 2.0, "take_profit_pct": 4.0},
        )
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            side="buy", reference_price=150.0, stop_loss_pct=2.0, take_profit_pct=4.0,
            sizing_pending=False, notional=1000.0,
        )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ALPACA_ORDERS_URL).mock(
                return_value=httpx.Response(
                    200,
                    headers={"x-request-id": "req-test-123"},
                    json=_alpaca_order_response(client_order_id=client_order_id, status="accepted", order_id="alpaca-order-1"),
                )
            )
            order_worker._process_envelope(engine, redis_client, envelope)
            sent_body = json.loads(mock.calls.last.request.content)

        assert sent_body["order_class"] == "bracket"
        # BUY : stop-loss sous le prix de référence, take-profit au-dessus.
        assert sent_body["stop_loss"] == {"stop_price": "147.00"}
        assert sent_body["take_profit"] == {"limit_price": "156.00"}
        assert sent_body["client_order_id"] == client_order_id

        order = _fetch_order(engine, client_order_id=client_order_id)
        assert order["status"] == "accepted"
        assert order["provider_order_id"] == "alpaca-order-1"
        assert order["provider_request_id"] == "req-test-123"
        assert order["submitted_at"] is not None

        events = _fetch_order_events(engine, order_id=order["id"])
        assert len(events) == 1
        assert events[0]["provider_request_id"] == "req-test-123"

        published = _drain(redis_client, Streams.ORDER_EVENTS)
        assert len(published) == 1
        assert published[0]["payload"]["status"] == "accepted"
        assert published[0]["payload"]["provider_order_id"] == "alpaca-order-1"

    def test_sell_side_bracket_legs_are_inverted(self, engine, redis_client):
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            side="sell", reference_price=100.0, stop_loss_pct=2.0, take_profit_pct=4.0,
            sizing_pending=False, quantity=5.0,
        )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ALPACA_ORDERS_URL).mock(
                return_value=httpx.Response(
                    200, headers={"x-request-id": "req-2"},
                    json=_alpaca_order_response(client_order_id=client_order_id, status="new"),
                )
            )
            order_worker._process_envelope(engine, redis_client, envelope)
            sent_body = json.loads(mock.calls.last.request.content)

        assert sent_body["stop_loss"] == {"stop_price": "102.00"}
        assert sent_body["take_profit"] == {"limit_price": "96.00"}
        assert sent_body["qty"] == "5.0"

    def test_order_rejected_by_alpaca(self, engine, redis_client):
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            sizing_pending=False, notional=1000.0,
        )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ALPACA_ORDERS_URL).mock(
                return_value=httpx.Response(422, json={"code": 40310000, "message": "symbole invalide"})
            )
            order_worker._process_envelope(engine, redis_client, envelope)

        order = _fetch_order(engine, client_order_id=client_order_id)
        assert order["status"] == "rejected"
        published = _drain(redis_client, Streams.ORDER_EVENTS)
        assert published[0]["payload"]["status"] == "rejected"
        assert published[0]["payload"]["code"] == 40310000

    def test_insufficient_funds_rejected(self, engine, redis_client):
        """§test P0 "Fonds insuffisants" — même chemin `AlpacaOrderRejected`
        que le rejet générique, message/code différents."""
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            sizing_pending=False, notional=1_000_000.0,
        )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ALPACA_ORDERS_URL).mock(
                return_value=httpx.Response(403, json={"code": 40310000, "message": "insufficient buying power"})
            )
            order_worker._process_envelope(engine, redis_client, envelope)

        order = _fetch_order(engine, client_order_id=f"zst-{risk_decision_id}")
        assert order["status"] == "rejected"
        events = _fetch_order_events(engine, order_id=order["id"])
        assert "insufficient" in events[0]["payload"]["message"]

    def test_upstream_error_is_not_caught_and_leaves_order_pending(self, engine, redis_client):
        """L'erreur transitoire remonte à l'appelant (`tick()` la retentera
        via `EventConsumer.fail`) — la ligne `orders` reste 'pending',
        jamais marquée en échec définitif pour une panne réseau/5xx."""
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            sizing_pending=False, notional=1000.0,
        )

        from order_worker.alpaca_trading_client import AlpacaTradingUpstreamError

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ALPACA_ORDERS_URL).mock(return_value=httpx.Response(500, json={"message": "internal error"}))
            with pytest.raises(AlpacaTradingUpstreamError):
                order_worker._process_envelope(engine, redis_client, envelope)

        order = _fetch_order(engine, client_order_id=f"zst-{risk_decision_id}")
        assert order["status"] == "pending"

    def test_duplicate_command_received_twice_only_calls_alpaca_once(self, engine, redis_client):
        """§test P0 "Doublon reçu deux fois"."""
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            sizing_pending=False, notional=1000.0,
        )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ALPACA_ORDERS_URL).mock(
                return_value=httpx.Response(
                    200, headers={"x-request-id": "req-dup"}, json=_alpaca_order_response(client_order_id=client_order_id, status="accepted")
                )
            )
            order_worker._process_envelope(engine, redis_client, envelope)
            order_worker._process_envelope(engine, redis_client, envelope)  # doublon — même risk_decision_id
            assert len(mock.calls) == 1

        assert len(_drain(redis_client, Streams.ORDER_EVENTS)) == 1
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM orders WHERE client_order_id = :cid"), {"cid": client_order_id}
            ).scalar_one()
        assert count == 1

    def test_worker_restarted_mid_order_retries_with_same_client_order_id(self, engine, redis_client):
        """§test P0 "Worker redémarré pendant un ordre" — une ligne
        `orders` en `status='pending'` existe déjà (simulateur d'un crash
        après l'INSERT mais avant la réponse Alpaca) : le retraitement de
        la MÊME commande doit retenter avec le même `client_order_id`,
        jamais créer une deuxième ligne."""
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id,
            sizing_pending=False, notional=1000.0,
        )

        pre_existing_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                order_worker._INSERT_ORDER_SQL,
                {
                    "id": pre_existing_id,
                    "user_id": ctx["user_id"],
                    "execution_context_id": ctx["execution_context_id"],
                    "strategy_id": strat_id,
                    "risk_decision_id": risk_decision_id,
                    "symbol": "AAPL",
                    "side": "buy",
                    "notional": 1000.0,
                    "quantity": None,
                    "order_type": "market",
                    "time_in_force": "day",
                    "stop_loss": json.dumps({"stop_loss_pct": 2.0}),
                    "take_profit": json.dumps({"take_profit_pct": 4.0}),
                    "status": "pending",
                    "idempotency_key": str(risk_decision_id),
                    "client_order_id": client_order_id,
                    "correlation_id": envelope.correlation_id,
                },
            )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ALPACA_ORDERS_URL).mock(
                return_value=httpx.Response(
                    200, headers={"x-request-id": "req-restart"}, json=_alpaca_order_response(client_order_id=client_order_id, status="accepted")
                )
            )
            order_worker._process_envelope(engine, redis_client, envelope)
            assert len(mock.calls) == 1
            assert json.loads(mock.calls.last.request.content)["client_order_id"] == client_order_id

        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM orders WHERE client_order_id = :cid"), {"cid": client_order_id}
            ).scalar_one()
        assert count == 1
        order = _fetch_order(engine, client_order_id=client_order_id)
        assert order["id"] == pre_existing_id
        assert order["status"] == "accepted"


# ----------------------------------------------------------------------
# WebSocket trade_updates -> mise à jour locale + réconciliation REST.
# ----------------------------------------------------------------------


class TestApplyTradeUpdateEvent:
    def test_updates_known_order_status_and_publishes(self, engine, redis_client):
        ctx = _make_context(engine, kind="PAPER")
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        order_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                order_worker._INSERT_ORDER_SQL,
                {
                    "id": order_id, "user_id": ctx["user_id"], "execution_context_id": ctx["execution_context_id"],
                    "strategy_id": strat_id, "risk_decision_id": risk_decision_id, "symbol": "AAPL", "side": "buy",
                    "notional": 1000.0, "quantity": None, "order_type": "market", "time_in_force": "day",
                    "stop_loss": "{}", "take_profit": "{}", "status": "accepted",
                    "idempotency_key": str(risk_decision_id), "client_order_id": client_order_id,
                    "correlation_id": uuid.uuid4(),
                },
            )

        event = {"event": "fill", "order": {"client_order_id": client_order_id, "id": "alpaca-1"}, "price": "151.20", "qty": "6"}
        order_worker._apply_trade_update_event(engine, redis_client, event)

        order = _fetch_order(engine, client_order_id=client_order_id)
        assert order["status"] == "fill"
        assert order["filled_at"] is not None
        events = _fetch_order_events(engine, order_id=order_id)
        assert events[0]["event_type"] == "order.fill"
        published = _drain(redis_client, Streams.ORDER_EVENTS)
        assert published[0]["payload"]["status"] == "fill"
        assert published[0]["payload"]["source"] == "websocket"

    def test_unknown_client_order_id_is_ignored(self, engine, redis_client):
        event = {"event": "fill", "order": {"client_order_id": "zst-unknown"}}
        order_worker._apply_trade_update_event(engine, redis_client, event)  # ne doit pas lever
        assert _drain(redis_client, Streams.ORDER_EVENTS) == []


class TestReconcileAfterReconnect:
    def test_reconciles_non_terminal_orders_via_rest(self, engine, redis_client):
        ctx = _make_context(engine, kind="PAPER")
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        order_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                order_worker._INSERT_ORDER_SQL,
                {
                    "id": order_id, "user_id": ctx["user_id"], "execution_context_id": ctx["execution_context_id"],
                    "strategy_id": strat_id, "risk_decision_id": risk_decision_id, "symbol": "AAPL", "side": "buy",
                    "notional": 1000.0, "quantity": None, "order_type": "market", "time_in_force": "day",
                    "stop_loss": "{}", "take_profit": "{}", "status": "new",
                    "idempotency_key": str(risk_decision_id), "client_order_id": client_order_id,
                    "correlation_id": uuid.uuid4(),
                },
            )
            conn.execute(
                text("UPDATE orders SET provider_order_id = :pid WHERE id = :id"), {"pid": "alpaca-provider-1", "id": order_id}
            )

        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{ALPACA_ORDERS_URL}/alpaca-provider-1").mock(
                return_value=httpx.Response(
                    200, headers={"x-request-id": "req-reconcile"},
                    json=_alpaca_order_response(client_order_id=client_order_id, status="fill", order_id="alpaca-provider-1"),
                )
            )
            order_worker._reconcile_after_reconnect(
                engine, redis_client, user_id=ctx["user_id"], api_key="k", secret_key="s"
            )

        order = _fetch_order(engine, client_order_id=client_order_id)
        assert order["status"] == "fill"
        published = _drain(redis_client, Streams.ORDER_EVENTS)
        assert published[0]["payload"]["status"] == "fill"
        assert published[0]["payload"]["source"] == "reconciliation_rest"

    def test_no_non_terminal_orders_is_noop(self, engine, redis_client):
        with respx.mock(assert_all_called=False) as mock:
            order_worker._reconcile_after_reconnect(engine, redis_client, user_id=uuid.uuid4(), api_key="k", secret_key="s")
        assert not mock.calls


class TestKillSwitchCancelSweep:
    """§B31 "Annuler ordres ouverts éligibles" — même construction directe
    d'une ligne `orders` déjà "ouverte" que `TestReconcileAfterReconnect`
    ci-dessus (voir docstring `_cancel_orders_for_kill_switch` : structurellement
    inatteignable par le vrai pipeline tant que B16 publie toujours
    `sizing_pending=true`, D040)."""

    def test_cancels_eligible_open_order_and_marks_pending_cancel(self, engine, redis_client):
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        order_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                order_worker._INSERT_ORDER_SQL,
                {
                    "id": order_id, "user_id": ctx["user_id"], "execution_context_id": ctx["execution_context_id"],
                    "strategy_id": strat_id, "risk_decision_id": risk_decision_id, "symbol": "AAPL", "side": "buy",
                    "notional": 1000.0, "quantity": None, "order_type": "market", "time_in_force": "day",
                    "stop_loss": "{}", "take_profit": "{}", "status": "accepted",
                    "idempotency_key": str(risk_decision_id), "client_order_id": client_order_id,
                    "correlation_id": uuid.uuid4(),
                },
            )
            conn.execute(
                text("UPDATE orders SET provider_order_id = :pid WHERE id = :id"),
                {"pid": "alpaca-kill-switch-1", "id": order_id},
            )
        set_trading_kill_switch_engaged(redis_client, True)
        accounts = order_worker._connected_accounts(engine)

        with respx.mock(assert_all_called=True) as mock:
            mock.delete(f"{ALPACA_ORDERS_URL}/alpaca-kill-switch-1").mock(return_value=httpx.Response(204))
            order_worker._cancel_orders_for_kill_switch(engine, redis_client, accounts)

        order = _fetch_order(engine, client_order_id=client_order_id)
        assert order["status"] == "pending_cancel"
        events = _fetch_order_events(engine, order_id=order_id)
        assert events[-1]["event_type"] == "order.cancel_requested"
        published = _drain(redis_client, Streams.ORDER_EVENTS)
        assert published[-1]["payload"]["status"] == "pending_cancel"
        assert published[-1]["payload"]["reason"] == "kill_switch"

    def test_terminal_orders_are_never_touched(self, engine, redis_client):
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        order_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                order_worker._INSERT_ORDER_SQL,
                {
                    "id": order_id, "user_id": ctx["user_id"], "execution_context_id": ctx["execution_context_id"],
                    "strategy_id": strat_id, "risk_decision_id": risk_decision_id, "symbol": "AAPL", "side": "buy",
                    "notional": 1000.0, "quantity": None, "order_type": "market", "time_in_force": "day",
                    "stop_loss": "{}", "take_profit": "{}", "status": "fill",
                    "idempotency_key": str(risk_decision_id), "client_order_id": client_order_id,
                    "correlation_id": uuid.uuid4(),
                },
            )
            conn.execute(
                text("UPDATE orders SET provider_order_id = :pid WHERE id = :id"),
                {"pid": "alpaca-already-filled", "id": order_id},
            )
        set_trading_kill_switch_engaged(redis_client, True)
        accounts = order_worker._connected_accounts(engine)

        with respx.mock(assert_all_called=False) as mock:
            order_worker._cancel_orders_for_kill_switch(engine, redis_client, accounts)
        assert not mock.calls, "un ordre déjà terminal (fill) ne doit jamais déclencher d'appel Alpaca"

        order = _fetch_order(engine, client_order_id=client_order_id)
        assert order["status"] == "fill"

    def test_no_open_orders_is_noop(self, engine, redis_client):
        set_trading_kill_switch_engaged(redis_client, True)
        with respx.mock(assert_all_called=False) as mock:
            order_worker._cancel_orders_for_kill_switch(engine, redis_client, [])
        assert not mock.calls

    def test_already_terminal_at_alpaca_between_read_and_cancel_is_handled_gracefully(self, engine, redis_client):
        """§course : notre lecture locale dit encore "accepted" mais Alpaca
        a déjà rempli/annulé l'ordre entre-temps — 422 attendu et absorbé,
        jamais une exception qui ferait planter le balayage entier."""
        ctx = _make_context(engine, kind="PAPER")
        _make_connected_account(engine, user_id=ctx["user_id"])
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        client_order_id = f"zst-{risk_decision_id}"
        order_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                order_worker._INSERT_ORDER_SQL,
                {
                    "id": order_id, "user_id": ctx["user_id"], "execution_context_id": ctx["execution_context_id"],
                    "strategy_id": strat_id, "risk_decision_id": risk_decision_id, "symbol": "AAPL", "side": "buy",
                    "notional": 1000.0, "quantity": None, "order_type": "market", "time_in_force": "day",
                    "stop_loss": "{}", "take_profit": "{}", "status": "accepted",
                    "idempotency_key": str(risk_decision_id), "client_order_id": client_order_id,
                    "correlation_id": uuid.uuid4(),
                },
            )
            conn.execute(
                text("UPDATE orders SET provider_order_id = :pid WHERE id = :id"),
                {"pid": "alpaca-race-1", "id": order_id},
            )
        set_trading_kill_switch_engaged(redis_client, True)
        accounts = order_worker._connected_accounts(engine)

        with respx.mock(assert_all_called=True) as mock:
            mock.delete(f"{ALPACA_ORDERS_URL}/alpaca-race-1").mock(
                return_value=httpx.Response(422, json={"message": "order already in filled state"})
            )
            order_worker._cancel_orders_for_kill_switch(engine, redis_client, accounts)  # ne doit pas lever

        order = _fetch_order(engine, client_order_id=client_order_id)
        assert order["status"] == "accepted", "statut local jamais forcé sur un échec d'annulation — la réconciliation s'en chargera"


# ----------------------------------------------------------------------
# tick() de bout en bout — vrai stream Redis / groupe de consommateurs.
# ----------------------------------------------------------------------


class TestTickEndToEnd:
    def test_tick_consumes_published_command_via_real_stream(self, engine, redis_client):
        """Contexte REPLAY : aucun compte connecté nécessaire, donc aucun
        `TradeUpdatesListener` ne démarre pendant ce `tick()` (voir
        docstring de la classe fixture — pas de compte 'connected' créé)."""
        ctx = _make_context(engine, kind="REPLAY")
        strat_id = _make_strategy(engine, user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"])
        risk_decision_id = _make_risk_decision(engine, execution_context_id=ctx["execution_context_id"], strategy_id=strat_id)
        envelope = _command_envelope(
            execution_context_id=ctx["execution_context_id"], user_id=ctx["user_id"], risk_decision_id=risk_decision_id, strategy_id=strat_id
        )

        from shared.eventbus import publish_event

        publish_event(redis_client, Streams.ORDER_COMMANDS, envelope)
        order_worker.tick(engine, redis_client)

        order = _fetch_order(engine, client_order_id=f"zst-{risk_decision_id}")
        assert order is not None
        assert order["status"] == "deferred_replay"
        assert len(_drain(redis_client, Streams.ORDER_EVENTS)) == 1

    def test_tick_dead_letters_invalid_payload_via_real_stream(self, engine, redis_client):
        ctx = _make_context(engine, kind="REPLAY")
        envelope = EventEnvelope(
            event_type="order.command.prepared",
            correlation_id=uuid.uuid4(),
            execution_context_id=ctx["execution_context_id"],
            user_id=ctx["user_id"],
            payload={"symbol": "AAPL"},
        )

        from shared.eventbus import publish_event

        publish_event(redis_client, Streams.ORDER_COMMANDS, envelope)
        order_worker.tick(engine, redis_client)

        assert len(_drain(redis_client, Streams.dead_letter(Streams.ORDER_COMMANDS))) == 1


# ----------------------------------------------------------------------
# Cycle de vie des TradeUpdatesListener — double injecté, aucun réseau.
# ----------------------------------------------------------------------


class _FakeListener:
    """Double minimal — mêmes méthodes que `TradeUpdatesListener`, aucune
    connexion réelle (même principe que les doubles de
    `test_mcp_session.py` pour `McpSessionManager`)."""

    instances: list[_FakeListener] = []

    def __init__(self, *, on_event, on_reconnected=None, **_kwargs) -> None:
        self.on_event = on_event
        self.on_reconnected = on_reconnected
        self.started_with: tuple[str, str] | None = None
        self.stopped = False
        _FakeListener.instances.append(self)

    def start(self, api_key: str, secret_key: str) -> None:
        self.started_with = (api_key, secret_key)

    def stop(self) -> None:
        self.stopped = True


class TestListenerLifecycle:
    @pytest.fixture(autouse=True)
    def _patch_listener(self, monkeypatch):
        _FakeListener.instances = []
        monkeypatch.setattr(order_worker, "TradeUpdatesListener", _FakeListener)
        yield

    def test_ensure_listener_starts_once_and_reuses(self):
        account_id, user_id = uuid.uuid4(), uuid.uuid4()
        first = order_worker._ensure_listener(account_id, user_id, "key", "secret", engine=None, redis_client=None)
        second = order_worker._ensure_listener(account_id, user_id, "key", "secret", engine=None, redis_client=None)
        assert first is second
        assert len(_FakeListener.instances) == 1
        assert first.started_with == ("key", "secret")

    def test_ensure_listener_restarts_on_credential_change(self):
        account_id, user_id = uuid.uuid4(), uuid.uuid4()
        order_worker._ensure_listener(account_id, user_id, "key", "secret", engine=None, redis_client=None)
        order_worker._ensure_listener(account_id, user_id, "key", "NEW-SECRET", engine=None, redis_client=None)
        assert len(_FakeListener.instances) == 1
        assert _FakeListener.instances[0].stopped is True
        assert _FakeListener.instances[0].started_with == ("key", "NEW-SECRET")

    def test_cleanup_stops_listener_for_disconnected_account(self):
        account_id, user_id = uuid.uuid4(), uuid.uuid4()
        order_worker._ensure_listener(account_id, user_id, "key", "secret", engine=None, redis_client=None)
        order_worker._cleanup_stale_listeners(active_account_ids=set())
        assert _FakeListener.instances[0].stopped is True
        assert account_id not in order_worker._listeners
