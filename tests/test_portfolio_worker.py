"""B18 — workers/portfolio_worker/main.py. Intégration réelle contre
PostgreSQL (aucun mock d'infra interne) — seule la frontière HTTP avec
Alpaca est mockée (`respx`), même discipline que `test_order_worker.py`
(B17)/`test_onboarding.py` (B07).

Contrairement à `test_order_worker.py`, ce module n'a besoin ni du SDK
`mcp` ni de Redis (`tick()` ne publie aucun événement, voir docstring de
`workers/portfolio_worker/main.py`) : ces tests tournent sous `.venv`
(backend), pas `.venv-agents`."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

os.environ.setdefault("APP_ENCRYPTION_KEY", "RB-l2-7BeTsBNRSaUSuU85CsRr1C18vHkEI3kMq7JiE=")

import portfolio_worker.main as portfolio_worker  # noqa: E402
from common.encryption import encrypt_secret  # noqa: E402
from sqlalchemy import text  # noqa: E402

ALPACA_ACCOUNT_URL = "https://paper-api.alpaca.markets/v2/account"
ALPACA_POSITIONS_URL = "https://paper-api.alpaca.markets/v2/positions"


@pytest.fixture()
def engine():
    from app.db import engine as _engine  # noqa: PLC0415 — après sys.path, volontaire

    return _engine


@pytest.fixture(autouse=True)
def _clean_state(engine):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM portfolio_snapshots"))
        conn.execute(text("DELETE FROM positions_snapshots"))
        conn.execute(text("DELETE FROM user_trading_accounts WHERE metadata_json->>'test' = 'portfolio_worker'"))
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'portfolio-worker-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'portfolio-worker-test-%'"))
        conn.commit()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM portfolio_snapshots"))
        conn.execute(text("DELETE FROM positions_snapshots"))
        conn.execute(text("DELETE FROM user_trading_accounts WHERE metadata_json->>'test' = 'portfolio_worker'"))
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'portfolio-worker-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'portfolio-worker-test-%'"))
        conn.commit()


def _make_context(engine, *, kind="PAPER") -> dict:
    user_id = uuid.uuid4()
    ctx_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, 'x', 'Portfolio Worker Test', true)"
            ),
            {"id": user_id, "email": f"portfolio-worker-test-{user_id}@zikosofttrader.local"},
        )
        conn.execute(
            text(
                "INSERT INTO execution_contexts (id, user_id, kind, label, is_active) "
                "VALUES (:id, :user_id, :kind, 'portfolio-worker-test', false)"
            ),
            {"id": ctx_id, "user_id": user_id, "kind": kind},
        )
    return {"user_id": user_id, "execution_context_id": ctx_id}


def _make_connected_account(engine, *, user_id) -> uuid.UUID:
    account_id = uuid.uuid4()
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
                "metadata": json.dumps({"test": "portfolio_worker"}),
            },
        )
    return account_id


def _account_json(**overrides) -> dict:
    body = {
        "cash": "50000.00",
        "buying_power": "100000.00",
        "portfolio_value": "150000.00",
        "equity": "150000.00",
        "last_equity": "149750.00",
    }
    body.update(overrides)
    return body


def _position_json(**overrides) -> dict:
    body = {
        "symbol": "AAPL",
        "qty": "10",
        "avg_entry_price": "150.00",
        "market_value": "1550.00",
        "unrealized_pl": "50.00",
    }
    body.update(overrides)
    return body


def _mock_alpaca(mock, *, account=None, positions=None):
    mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(200, json=account or _account_json()))
    mock.get(ALPACA_POSITIONS_URL).mock(
        return_value=httpx.Response(200, json=positions if positions is not None else [_position_json()])
    )


class TestTickWritesSnapshots:
    def test_writes_one_portfolio_snapshot_and_matching_positions(self, engine):
        ctx = _make_context(engine)
        _make_connected_account(engine, user_id=ctx["user_id"])

        with respx.mock(assert_all_called=True) as mock:
            _mock_alpaca(mock, positions=[_position_json(), _position_json(symbol="MSFT")])
            portfolio_worker.tick(engine, redis_client=None)

        with engine.connect() as conn:
            portfolio_rows = conn.execute(
                text("SELECT * FROM portfolio_snapshots WHERE execution_context_id = :id"),
                {"id": ctx["execution_context_id"]},
            ).mappings().all()
            position_rows = conn.execute(
                text("SELECT * FROM positions_snapshots WHERE execution_context_id = :id ORDER BY symbol"),
                {"id": ctx["execution_context_id"]},
            ).mappings().all()

        assert len(portfolio_rows) == 1
        snapshot = portfolio_rows[0]
        assert float(snapshot["cash"]) == 50000.0
        assert float(snapshot["buying_power"]) == 100000.0
        assert float(snapshot["portfolio_value"]) == 150000.0
        assert float(snapshot["daily_pl"]) == 250.0  # equity(150000) - last_equity(149750)
        assert float(snapshot["total_pl"]) == 0.0  # premier snapshot -> sa propre référence

        assert len(position_rows) == 2
        assert {r["symbol"] for r in position_rows} == {"AAPL", "MSFT"}
        # §B18 — même snapshot_at que le portfolio_snapshot du même tick (voir
        # docstring de `_write_snapshot` / `backend/app/portfolio.py::latest_positions`).
        assert all(r["snapshot_at"] == snapshot["snapshot_at"] for r in position_rows)

    def test_no_open_positions_writes_zero_position_rows(self, engine):
        ctx = _make_context(engine)
        _make_connected_account(engine, user_id=ctx["user_id"])

        with respx.mock(assert_all_called=True) as mock:
            _mock_alpaca(mock, positions=[])
            portfolio_worker.tick(engine, redis_client=None)

        with engine.connect() as conn:
            portfolio_rows = conn.execute(
                text("SELECT id FROM portfolio_snapshots WHERE execution_context_id = :id"),
                {"id": ctx["execution_context_id"]},
            ).mappings().all()
            position_rows = conn.execute(
                text("SELECT id FROM positions_snapshots WHERE execution_context_id = :id"),
                {"id": ctx["execution_context_id"]},
            ).mappings().all()
        assert len(portfolio_rows) == 1
        assert len(position_rows) == 0

    def test_missing_equity_fields_leave_daily_pl_null_not_zero(self, engine):
        ctx = _make_context(engine)
        _make_connected_account(engine, user_id=ctx["user_id"])
        body = _account_json()
        del body["equity"]
        del body["last_equity"]

        with respx.mock(assert_all_called=True) as mock:
            _mock_alpaca(mock, account=body)
            portfolio_worker.tick(engine, redis_client=None)

        with engine.connect() as conn:
            snapshot = conn.execute(
                text("SELECT daily_pl FROM portfolio_snapshots WHERE execution_context_id = :id"),
                {"id": ctx["execution_context_id"]},
            ).mappings().first()
        assert snapshot["daily_pl"] is None

    def test_second_tick_computes_total_pl_against_earliest_snapshot(self, engine):
        ctx = _make_context(engine)
        _make_connected_account(engine, user_id=ctx["user_id"])

        with respx.mock(assert_all_called=True) as mock:
            _mock_alpaca(mock, account=_account_json(portfolio_value="150000.00"))
            portfolio_worker.tick(engine, redis_client=None)

        # Force le prochain tick à passer le cooldown (voir test dédié
        # ci-dessous pour le cooldown lui-même).
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE portfolio_snapshots SET snapshot_at = :past WHERE execution_context_id = :id"),
                {"past": datetime.now(UTC) - timedelta(seconds=portfolio_worker.SNAPSHOT_INTERVAL_SECONDS + 5), "id": ctx["execution_context_id"]},
            )

        with respx.mock(assert_all_called=True) as mock:
            _mock_alpaca(mock, account=_account_json(portfolio_value="165000.00"))
            portfolio_worker.tick(engine, redis_client=None)

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT portfolio_value, total_pl FROM portfolio_snapshots "
                    "WHERE execution_context_id = :id ORDER BY snapshot_at ASC"
                ),
                {"id": ctx["execution_context_id"]},
            ).mappings().all()
        assert len(rows) == 2
        assert float(rows[0]["total_pl"]) == 0.0
        assert float(rows[1]["total_pl"]) == 15000.0  # 165000 - 150000 (le premier snapshot, la référence)


class TestCooldown:
    def test_second_tick_within_interval_is_skipped(self, engine):
        ctx = _make_context(engine)
        _make_connected_account(engine, user_id=ctx["user_id"])

        with respx.mock(assert_all_called=True) as mock:
            _mock_alpaca(mock)
            portfolio_worker.tick(engine, redis_client=None)

        # 2e tick immédiatement après — aucun appel Alpaca attendu (le mock
        # `assert_all_called=False` sans route enregistrée lèverait de toute
        # façon si un appel était fait à une URL non mockée ; ici on ne mock
        # RIEN du tout et on vérifie qu'aucune requête ne part).
        with respx.mock(assert_all_called=False) as mock:
            portfolio_worker.tick(engine, redis_client=None)
            assert len(mock.calls) == 0

        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM portfolio_snapshots WHERE execution_context_id = :id"),
                {"id": ctx["execution_context_id"]},
            ).scalar_one()
        assert count == 1

    def test_survives_restart_via_db_state_not_in_memory(self, engine):
        """§B18 — le cooldown est basé sur `MAX(snapshot_at)` en base, pas
        sur un dict en mémoire du process : un snapshot déjà écrit "empêche"
        un nouveau tick même si le worker (et son état en mémoire) vient de
        redémarrer, simulé ici en appelant `tick()` sans jamais avoir
        d'état de process partagé entre les deux appels (aucun état module-
        level n'est lu par `tick()` pour cette décision)."""
        ctx = _make_context(engine)
        _make_connected_account(engine, user_id=ctx["user_id"])
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO portfolio_snapshots "
                    "(id, user_id, execution_context_id, cash, buying_power, portfolio_value, "
                    " raw_provider_payload, snapshot_at) "
                    "VALUES (:id, :user_id, :ctx_id, 1, 1, 1, '{}'::jsonb, :now)"
                ),
                {"id": uuid.uuid4(), "user_id": ctx["user_id"], "ctx_id": ctx["execution_context_id"], "now": datetime.now(UTC)},
            )

        with respx.mock(assert_all_called=False) as mock:
            portfolio_worker.tick(engine, redis_client=None)
            assert len(mock.calls) == 0


class TestFailureIsolation:
    def test_one_account_alpaca_failure_does_not_block_others(self, engine):
        ctx1 = _make_context(engine)
        ctx2 = _make_context(engine)
        _make_connected_account(engine, user_id=ctx1["user_id"])
        _make_connected_account(engine, user_id=ctx2["user_id"])

        # Un seul mock pour les deux comptes (mêmes URLs Alpaca) : on ne
        # peut pas différencier par compte ici, donc ce test vérifie plutôt
        # qu'une erreur Alpaca (401) n'empêche pas `tick()` de se terminer
        # proprement pour les DEUX comptes plutôt que de lever.
        with respx.mock(assert_all_called=False) as mock:
            mock.get(ALPACA_ACCOUNT_URL).mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
            mock.get(ALPACA_POSITIONS_URL).mock(return_value=httpx.Response(200, json=[]))
            portfolio_worker.tick(engine, redis_client=None)  # ne doit pas lever

        with engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM portfolio_snapshots")).scalar_one()
        assert count == 0

    def test_no_paper_context_is_skipped_not_crashed(self, engine):
        user_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, display_name, is_active) "
                    "VALUES (:id, :email, 'x', 'Portfolio Worker Test', true)"
                ),
                {"id": user_id, "email": f"portfolio-worker-test-{user_id}@zikosofttrader.local"},
            )
        _make_connected_account(engine, user_id=user_id)

        with respx.mock(assert_all_called=False) as mock:
            portfolio_worker.tick(engine, redis_client=None)  # ne doit pas lever
            assert len(mock.calls) == 0
