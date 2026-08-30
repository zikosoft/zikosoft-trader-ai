"""B03 — schéma PostgreSQL : contraintes clés (idempotence, isolation contexte)."""

from __future__ import annotations

import uuid

import pytest
from app.models import ExecutionContext, Order, User
from sqlalchemy.exc import IntegrityError


def _make_user(db_session) -> User:
    user = User(
        email=f"test-{uuid.uuid4()}@zikosofttrader.local",
        password_hash="x",
        display_name="Test",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _make_context(db_session, user: User, kind: str = "PAPER") -> ExecutionContext:
    ctx = ExecutionContext(kind=kind, label=kind, user_id=user.id)
    db_session.add(ctx)
    db_session.flush()
    return ctx


def test_duplicate_idempotency_key_rejected(db_session):
    user = _make_user(db_session)
    ctx = _make_context(db_session, user)
    idem_key = f"idem-{uuid.uuid4()}"

    order1 = Order(
        user_id=user.id, execution_context_id=ctx.id, symbol="AAPL", side="buy", notional=1500,
        order_type="market", time_in_force="day", status="pending",
        idempotency_key=idem_key, client_order_id=f"client-{uuid.uuid4()}", correlation_id=uuid.uuid4(),
    )
    db_session.add(order1)
    db_session.commit()

    order2 = Order(
        user_id=user.id, execution_context_id=ctx.id, symbol="AAPL", side="buy", notional=1500,
        order_type="market", time_in_force="day", status="pending",
        idempotency_key=idem_key, client_order_id=f"client-{uuid.uuid4()}", correlation_id=uuid.uuid4(),
    )
    db_session.add(order2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_execution_context_isolation_is_structural(db_session):
    """Vérifie que `execution_context_id` est bien obligatoire (NOT NULL) sur
    `orders` — c'est la garantie structurelle derrière l'isolation Replay/Paper
    (risque R06). Le filtrage applicatif reste à tester en B06."""
    user = _make_user(db_session)
    order = Order(
        user_id=user.id, symbol="AAPL", side="buy", notional=1500, order_type="market",
        time_in_force="day", status="pending", idempotency_key=str(uuid.uuid4()),
        client_order_id=str(uuid.uuid4()), correlation_id=uuid.uuid4(),
    )
    db_session.add(order)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
