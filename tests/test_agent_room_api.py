"""B28 — Agent Room (`GET /api/agents/room/*`). Contre PostgreSQL/Redis
réels et l'app FastAPI réelle (TestClient), aucun mock — insère directement
`agent_messages` (ce que `agents/strategy_agent/main.py`/
`agents/risk_critic_agent/main.py`/`workers/risk_engine/main.py` écrivent
désormais réellement, D073, testé séparément dans
`test_strategy_agent.py`/`test_risk_critic_agent.py`/`test_risk_engine.py`),
`agent_decisions`/`risk_decisions`/`orders`/`strategies` (mêmes principes
que `test_market_api.py`, B27)."""

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
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code LIKE 'agent_room_test_%'"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM orders"))
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code LIKE 'agent_room_test_%'"))
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


def _insert_agent_message(
    *,
    user_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    agent_type: str = "strategy_agent",
    conversation_thread_id: uuid.UUID | None = None,
    state: str = "completed",
    content: str = "signal détecté",
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> uuid.UUID:
    message_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_messages "
                "(id, user_id, execution_context_id, agent_type, conversation_thread_id, state, content, "
                " payload, occurred_at) "
                "VALUES (:id, :user_id, :ctx_id, :agent_type, :thread_id, :state, :content, "
                " CAST(:payload AS jsonb), :occurred_at)"
            ),
            {
                "id": message_id,
                "user_id": user_id,
                "ctx_id": execution_context_id,
                "agent_type": agent_type,
                "thread_id": conversation_thread_id or uuid.uuid4(),
                "state": state,
                "content": content,
                "payload": json.dumps(payload or {}),
                "occurred_at": occurred_at or datetime.now(UTC),
            },
        )
    return message_id


def _insert_agent_decision(
    *,
    execution_context_id: uuid.UUID,
    symbol: str = "AAPL",
    strategy_id: uuid.UUID | None = None,
    agent_type: str = "strategy_agent",
    decision_type: str = "PROPOSAL",
    outcome: str = "BUY",
    confidence: int | None = 7500,
    reasoning: dict | None = None,
    risk_flags: list | None = None,
    market_data_timestamp: str | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    decision_id = uuid.uuid4()
    created_at = created_at or datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_decisions "
                "(id, execution_context_id, strategy_id, agent_type, decision_type, outcome, confidence, "
                " reasoning, risk_flags, market_data_timestamp, correlation_id, created_at, updated_at) "
                "VALUES (:id, :ctx_id, :strategy_id, :agent_type, :decision_type, :outcome, :confidence, "
                " CAST(:reasoning AS jsonb), CAST(:risk_flags AS jsonb), :market_data_timestamp, :correlation_id, "
                " :created_at, :created_at)"
            ),
            {
                "id": decision_id,
                "ctx_id": execution_context_id,
                "strategy_id": strategy_id,
                "agent_type": agent_type,
                "decision_type": decision_type,
                "outcome": outcome,
                "confidence": confidence,
                "reasoning": json.dumps(reasoning if reasoning is not None else {"text": "raisonnement", "symbol": symbol}),
                "risk_flags": json.dumps(risk_flags or []),
                "market_data_timestamp": market_data_timestamp or created_at.isoformat(),
                "correlation_id": uuid.uuid4(),
                "created_at": created_at,
            },
        )
    return decision_id


def _insert_risk_decision(
    *,
    execution_context_id: uuid.UUID,
    agent_decision_id: uuid.UUID,
    outcome: str = "REJECTED",
    reasons: list | None = None,
    adjustments: dict | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    risk_decision_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO risk_decisions "
                "(id, execution_context_id, agent_decision_id, outcome, reasons, adjustments, correlation_id, "
                " created_at, updated_at) "
                "VALUES (:id, :ctx_id, :agent_decision_id, :outcome, CAST(:reasons AS jsonb), "
                " CAST(:adjustments AS jsonb), :correlation_id, :created_at, :created_at)"
            ),
            {
                "id": risk_decision_id,
                "ctx_id": execution_context_id,
                "agent_decision_id": agent_decision_id,
                "outcome": outcome,
                "reasons": json.dumps(reasons or ["daily_loss_limit_exceeded"]),
                "adjustments": json.dumps(adjustments or {}),
                "correlation_id": uuid.uuid4(),
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return risk_decision_id


def _insert_order(
    *,
    user_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    risk_decision_id: uuid.UUID | None = None,
    symbol: str = "AAPL",
    side: str = "buy",
    status: str = "filled",
    quantity: float | None = 10.0,
    created_at: datetime | None = None,
) -> uuid.UUID:
    order_id = uuid.uuid4()
    unique = uuid.uuid4().hex[:12]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO orders "
                "(id, user_id, execution_context_id, risk_decision_id, symbol, side, quantity, order_type, "
                " time_in_force, status, idempotency_key, client_order_id, correlation_id, filled_at, "
                " submitted_at, created_at, updated_at) "
                "VALUES (:id, :user_id, :ctx_id, :risk_decision_id, :symbol, :side, :quantity, 'market', 'day', "
                " :status, :idem_key, :client_order_id, :correlation_id, :filled_at, :submitted_at, :created_at, "
                " :created_at)"
            ),
            {
                "id": order_id,
                "user_id": user_id,
                "ctx_id": execution_context_id,
                "risk_decision_id": risk_decision_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "status": status,
                "idem_key": f"test-{unique}",
                "client_order_id": f"test-client-{unique}",
                "correlation_id": uuid.uuid4(),
                "filled_at": created_at or (datetime.now(UTC) if status == "filled" else None),
                "submitted_at": created_at or datetime.now(UTC),
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return order_id


def _make_strategy(*, user_id: uuid.UUID, execution_context_id: uuid.UUID, name: str = "Test Strategy") -> uuid.UUID:
    type_code = f"agent_room_test_{uuid.uuid4().hex[:8]}"
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
                "(id, user_id, execution_context_id, strategy_definition_id, name, definition_version, "
                " parameters, symbols, risk_configuration, status) "
                "VALUES (:id, :user_id, :ctx_id, :def_id, :name, '1.0.0', '{}'::jsonb, '[]'::jsonb, "
                " '{}'::jsonb, 'ACTIVE')"
            ),
            {"id": strat_id, "user_id": user_id, "ctx_id": execution_context_id, "def_id": def_id, "name": name},
        )
    return strat_id


class TestAuthRequired:
    def test_messages_requires_auth(self, client):
        response = client.get("/api/agents/room/messages")
        assert response.status_code == 401

    def test_decision_chain_requires_auth(self, client):
        response = client.get(
            "/api/agents/room/decision-chain",
            params={"strategy_id": str(uuid.uuid4()), "symbol": "AAPL", "market_data_timestamp": "x"},
        )
        assert response.status_code == 401


class TestNoActiveContext:
    @pytest.mark.parametrize(
        "path,params",
        [
            ("/api/agents/room/messages", {}),
            (
                "/api/agents/room/decision-chain",
                {"strategy_id": str(uuid.uuid4()), "symbol": "AAPL", "market_data_timestamp": "x"},
            ),
        ],
    )
    def test_requires_active_context(self, logged_in_client, path, params):
        response = logged_in_client.get(path, params=params)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestMessages:
    def test_empty_when_nothing_written(self, paper_client):
        response = paper_client.get("/api/agents/room/messages")
        assert response.status_code == 200
        assert response.json()["messages"] == []

    def test_returned_chronologically_ascending(self, paper_client, demo_user_id, paper_context_id):
        older = datetime.now(UTC) - timedelta(minutes=5)
        newer = datetime.now(UTC)
        _insert_agent_message(
            user_id=demo_user_id, execution_context_id=paper_context_id, content="plus récent", occurred_at=newer
        )
        _insert_agent_message(
            user_id=demo_user_id, execution_context_id=paper_context_id, content="plus ancien", occurred_at=older
        )
        response = paper_client.get("/api/agents/room/messages")
        assert response.status_code == 200
        contents = [m["content"] for m in response.json()["messages"]]
        assert contents == ["plus ancien", "plus récent"]

    def test_full_shape_including_all_four_agent_types(self, paper_client, demo_user_id, paper_context_id):
        for agent_type, state in [
            ("strategy_agent", "completed"),
            ("risk_critic_agent", "rejected"),
            ("risk_engine", "completed"),
            ("execution_explanation_agent", "completed"),
        ]:
            _insert_agent_message(
                user_id=demo_user_id,
                execution_context_id=paper_context_id,
                agent_type=agent_type,
                state=state,
                payload={"symbol": "AAPL", "outcome": "BUY"},
            )
        response = paper_client.get("/api/agents/room/messages")
        assert response.status_code == 200
        messages = response.json()["messages"]
        assert {m["agent_type"] for m in messages} == {
            "strategy_agent",
            "risk_critic_agent",
            "risk_engine",
            "execution_explanation_agent",
        }
        assert all("id" in m and "occurred_at" in m and "payload" in m for m in messages)

    def test_scoped_to_active_context(self, paper_client, demo_user_id, paper_context_id):
        # Un message écrit pour un AUTRE contexte (ex. REPLAY du même
        # utilisateur) ne doit jamais fuiter dans le Live Debate du contexte
        # actif (§R06) — voir `test_market_api.py::TestBars` pour le même
        # principe côté B27.
        with engine.connect() as conn:
            other_ctx = conn.execute(
                text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
                {"uid": demo_user_id},
            ).scalar_one()
        _insert_agent_message(user_id=demo_user_id, execution_context_id=other_ctx, content="autre contexte")
        response = paper_client.get("/api/agents/room/messages")
        assert response.status_code == 200
        assert response.json()["messages"] == []

    def test_limit_is_honored(self, paper_client, demo_user_id, paper_context_id):
        for i in range(5):
            _insert_agent_message(user_id=demo_user_id, execution_context_id=paper_context_id, content=f"msg-{i}")
        response = paper_client.get("/api/agents/room/messages", params={"limit": 2})
        assert response.status_code == 200
        assert len(response.json()["messages"]) == 2


class TestDecisionChain:
    def test_proposal_only_chain_is_honestly_partial(self, paper_client, demo_user_id, paper_context_id):
        strategy_id = _make_strategy(user_id=demo_user_id, execution_context_id=paper_context_id)
        mdt = datetime.now(UTC).isoformat()
        _insert_agent_decision(
            execution_context_id=paper_context_id,
            strategy_id=strategy_id,
            decision_type="PROPOSAL",
            outcome="BUY",
            market_data_timestamp=mdt,
        )
        response = paper_client.get(
            "/api/agents/room/decision-chain",
            params={"strategy_id": str(strategy_id), "symbol": "AAPL", "market_data_timestamp": mdt},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["proposal"]["outcome"] == "BUY"
        assert body["critique"] is None
        assert body["risk_decision"] is None
        assert body["explanation"] is None
        assert body["order"] is None
        assert body["strategy_name"] == "Test Strategy"

    def test_full_chain_including_order(self, paper_client, demo_user_id, paper_context_id):
        strategy_id = _make_strategy(user_id=demo_user_id, execution_context_id=paper_context_id)
        mdt = datetime.now(UTC).isoformat()
        _insert_agent_decision(
            execution_context_id=paper_context_id,
            strategy_id=strategy_id,
            decision_type="PROPOSAL",
            outcome="BUY",
            market_data_timestamp=mdt,
        )
        critique_id = _insert_agent_decision(
            execution_context_id=paper_context_id,
            strategy_id=strategy_id,
            agent_type="risk_critic_agent",
            decision_type="CRITIQUE",
            outcome="APPROVE",
            market_data_timestamp=mdt,
        )
        risk_decision_id = _insert_risk_decision(
            execution_context_id=paper_context_id, agent_decision_id=critique_id, outcome="APPROVED", reasons=[]
        )
        _insert_agent_decision(
            execution_context_id=paper_context_id,
            strategy_id=strategy_id,
            agent_type="execution_explanation_agent",
            decision_type="EXPLANATION",
            outcome="APPROVED",
            reasoning={
                "risk_decision_id": str(risk_decision_id),
                "novice_summary": "Ordre approuvé.",
                "expert_summary": "Tous les contrôles étaient nominaux.",
            },
            market_data_timestamp=mdt,
        )
        order_id = _insert_order(
            user_id=demo_user_id, execution_context_id=paper_context_id, risk_decision_id=risk_decision_id
        )

        response = paper_client.get(
            "/api/agents/room/decision-chain",
            params={"strategy_id": str(strategy_id), "symbol": "AAPL", "market_data_timestamp": mdt},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["proposal"]["outcome"] == "BUY"
        assert body["critique"]["outcome"] == "APPROVE"
        assert body["risk_decision"]["outcome"] == "APPROVED"
        assert body["explanation"]["novice_summary"] == "Ordre approuvé."
        assert body["order"]["id"] == str(order_id)

    def test_rejected_chain_has_no_order(self, paper_client, demo_user_id, paper_context_id):
        strategy_id = _make_strategy(user_id=demo_user_id, execution_context_id=paper_context_id)
        mdt = datetime.now(UTC).isoformat()
        critique_id = _insert_agent_decision(
            execution_context_id=paper_context_id,
            strategy_id=strategy_id,
            agent_type="risk_critic_agent",
            decision_type="CRITIQUE",
            outcome="REJECT",
            market_data_timestamp=mdt,
        )
        _insert_risk_decision(
            execution_context_id=paper_context_id,
            agent_decision_id=critique_id,
            outcome="REJECTED",
            reasons=["daily_loss_limit_exceeded"],
        )
        response = paper_client.get(
            "/api/agents/room/decision-chain",
            params={"strategy_id": str(strategy_id), "symbol": "AAPL", "market_data_timestamp": mdt},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["risk_decision"]["outcome"] == "REJECTED"
        assert body["order"] is None

    def test_unknown_window_returns_all_null_not_404(self, paper_client, demo_user_id, paper_context_id):
        # Fenêtre jamais atteinte (course entre deux ticks, ou clic sur un
        # ancien lien) — état honnêtement vide, jamais une erreur 404 (voir
        # docstring de `backend/app/agent_room.py`).
        strategy_id = _make_strategy(user_id=demo_user_id, execution_context_id=paper_context_id)
        response = paper_client.get(
            "/api/agents/room/decision-chain",
            params={"strategy_id": str(strategy_id), "symbol": "AAPL", "market_data_timestamp": "2026-01-01T00:00:00+00:00"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["proposal"] is None
        assert body["strategy_name"] == "Test Strategy"

    def test_requires_active_context_isolation(self, paper_client, demo_user_id, paper_context_id):
        # Une décision écrite pour un AUTRE contexte ne doit jamais fuiter
        # (§R06).
        with engine.connect() as conn:
            other_ctx = conn.execute(
                text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
                {"uid": demo_user_id},
            ).scalar_one()
        strategy_id = _make_strategy(user_id=demo_user_id, execution_context_id=other_ctx)
        mdt = datetime.now(UTC).isoformat()
        _insert_agent_decision(
            execution_context_id=other_ctx,
            strategy_id=strategy_id,
            decision_type="PROPOSAL",
            outcome="BUY",
            market_data_timestamp=mdt,
        )
        response = paper_client.get(
            "/api/agents/room/decision-chain",
            params={"strategy_id": str(strategy_id), "symbol": "AAPL", "market_data_timestamp": mdt},
        )
        assert response.status_code == 200
        assert response.json()["proposal"] is None
