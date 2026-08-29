"""B26 — Résumé Agent Room et Risque (`GET /api/agents/decisions/recent`,
`GET /api/risk/decisions/recent`). Contre PostgreSQL/Redis réels et l'app
FastAPI réelle (TestClient), aucun mock — insère directement des
`agent_decisions`/`risk_decisions` (ce que le Strategy Agent/Risk Critic
Agent, B13/B14, et le Risk Engine déterministe, B15, écriraient réellement),
même principe que `test_order_worker.py::_make_risk_decision`."""

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
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
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


def _insert_agent_decision(
    *,
    execution_context_id: uuid.UUID,
    agent_type: str = "strategy_agent",
    decision_type: str = "PROPOSAL",
    outcome: str = "BUY",
    confidence: int | None = 7500,
    created_at: datetime | None = None,
) -> uuid.UUID:
    decision_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_decisions "
                "(id, execution_context_id, strategy_id, agent_type, decision_type, outcome, confidence, "
                " reasoning, risk_flags, market_data_timestamp, correlation_id, created_at, updated_at) "
                "VALUES (:id, :ctx_id, NULL, :agent_type, :decision_type, :outcome, :confidence, "
                " '{}'::jsonb, '[]'::jsonb, :market_data_timestamp, :correlation_id, :created_at, :created_at)"
            ),
            {
                "id": decision_id,
                "ctx_id": execution_context_id,
                "agent_type": agent_type,
                "decision_type": decision_type,
                "outcome": outcome,
                "confidence": confidence,
                "market_data_timestamp": datetime.now(UTC).isoformat(),
                "correlation_id": uuid.uuid4(),
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return decision_id


def _insert_risk_decision(
    *,
    execution_context_id: uuid.UUID,
    agent_decision_id: uuid.UUID,
    outcome: str = "APPROVED",
    created_at: datetime | None = None,
) -> uuid.UUID:
    risk_decision_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO risk_decisions "
                "(id, execution_context_id, agent_decision_id, outcome, reasons, adjustments, correlation_id, "
                " created_at, updated_at) "
                "VALUES (:id, :ctx_id, :agent_decision_id, :outcome, '[]'::jsonb, '{}'::jsonb, :correlation_id, "
                " :created_at, :created_at)"
            ),
            {
                "id": risk_decision_id,
                "ctx_id": execution_context_id,
                "agent_decision_id": agent_decision_id,
                "outcome": outcome,
                "correlation_id": uuid.uuid4(),
                "created_at": created_at or datetime.now(UTC),
            },
        )
    return risk_decision_id


class TestAuthRequired:
    def test_agent_decisions_requires_auth(self, client):
        assert client.get("/api/agents/decisions/recent").status_code == 401

    def test_risk_decisions_requires_auth(self, client):
        assert client.get("/api/risk/decisions/recent").status_code == 401


class TestNoActiveContext:
    def test_agent_decisions_without_active_context(self, logged_in_client):
        response = logged_in_client.get("/api/agents/decisions/recent")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_risk_decisions_without_active_context(self, logged_in_client):
        assert logged_in_client.get("/api/risk/decisions/recent").status_code == 400


class TestRecentAgentDecisions:
    def test_no_activity_yet_returns_empty_list(self, paper_client):
        response = paper_client.get("/api/agents/decisions/recent")
        assert response.status_code == 200
        assert response.json()["decisions"] == []

    def test_returns_most_recent_first(self, paper_client, paper_context_id):
        now = datetime.now(UTC)
        _insert_agent_decision(execution_context_id=paper_context_id, outcome="HOLD", created_at=now - timedelta(minutes=5))
        _insert_agent_decision(execution_context_id=paper_context_id, outcome="BUY", created_at=now)

        response = paper_client.get("/api/agents/decisions/recent")
        decisions = response.json()["decisions"]
        assert [d["outcome"] for d in decisions] == ["BUY", "HOLD"]

    def test_isolated_by_execution_context(self, paper_client, logged_in_client, demo_user_id, paper_context_id):
        with engine.connect() as conn:
            replay_ctx_id = conn.execute(
                text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
                {"uid": demo_user_id},
            ).scalar_one()
        _insert_agent_decision(execution_context_id=replay_ctx_id, outcome="SELL")

        response = paper_client.get("/api/agents/decisions/recent")
        assert response.json()["decisions"] == []


class TestRecentRiskDecisions:
    def test_no_activity_yet_returns_empty_list(self, paper_client):
        response = paper_client.get("/api/risk/decisions/recent")
        assert response.status_code == 200
        assert response.json()["decisions"] == []

    def test_returns_most_recent_first_with_real_outcome(self, paper_client, paper_context_id):
        now = datetime.now(UTC)
        first_decision = _insert_agent_decision(execution_context_id=paper_context_id, created_at=now - timedelta(minutes=5))
        second_decision = _insert_agent_decision(execution_context_id=paper_context_id, created_at=now)
        _insert_risk_decision(
            execution_context_id=paper_context_id,
            agent_decision_id=first_decision,
            outcome="REJECTED",
            created_at=now - timedelta(minutes=5),
        )
        _insert_risk_decision(
            execution_context_id=paper_context_id, agent_decision_id=second_decision, outcome="APPROVED", created_at=now
        )

        response = paper_client.get("/api/risk/decisions/recent")
        decisions = response.json()["decisions"]
        assert [d["outcome"] for d in decisions] == ["APPROVED", "REJECTED"]

    def test_isolated_by_execution_context(self, paper_client, logged_in_client, demo_user_id, paper_context_id):
        with engine.connect() as conn:
            replay_ctx_id = conn.execute(
                text("SELECT id FROM execution_contexts WHERE user_id = :uid AND kind = 'REPLAY'"),
                {"uid": demo_user_id},
            ).scalar_one()
        replay_decision = _insert_agent_decision(execution_context_id=replay_ctx_id)
        _insert_risk_decision(execution_context_id=replay_ctx_id, agent_decision_id=replay_decision)

        response = paper_client.get("/api/risk/decisions/recent")
        assert response.json()["decisions"] == []
