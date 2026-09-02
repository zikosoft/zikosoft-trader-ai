"""B15 — workers/risk_engine/main.py::tick(). Intégration réelle contre
PostgreSQL/Redis (aucun mock d'infra interne, aucune frontière IA à mocker
ici — le Risk Engine est volontairement non-IA, §D005). Publie
`risk.critique.completed` directement (sans passer par un vrai Risk Critic
Agent), en insérant d'abord la ligne `agent_decisions` CRITIQUE
correspondante à la main — même principe que `test_risk_critic_agent.py`
pour `strategy.proposal.created`.

Contrairement à `test_risk_critic_agent.py`, ce module N'A PAS besoin du SDK
`anthropic` (le Risk Engine ne fait aucun appel IA) : ces tests tournent
sous `.venv` (backend), pas `.venv-agents`."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

import risk_engine.main as risk_engine  # noqa: E402
from app.db import engine as _engine  # noqa: E402

from shared.eventbus import publish_event  # noqa: E402
from shared.events import EventEnvelope, Streams  # noqa: E402
from shared.risk_governance import (  # noqa: E402
    TRADING_KILL_SWITCH_REDIS_KEY,
    set_trading_kill_switch_engaged,
)


@pytest.fixture()
def engine():
    return _engine

_CRITIQUE_INSERT_SQL = text(
    """
    INSERT INTO agent_decisions
        (id, execution_context_id, strategy_id, agent_type, decision_type, outcome, confidence,
         reasoning, risk_flags, market_data_timestamp, correlation_id)
    VALUES
        (:id, :execution_context_id, :strategy_id, 'risk_critic_agent', 'CRITIQUE', :outcome, :confidence,
         CAST(:reasoning AS jsonb), CAST(:risk_flags AS jsonb), :market_data_timestamp, :correlation_id)
    """
)


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    with _engine.connect() as conn:
        # §D042/B18 — portfolio_snapshots/positions_snapshots référencent
        # execution_contexts (FK sans CASCADE, voir ExecutionContextMixin) :
        # doivent être nettoyés AVANT execution_contexts ci-dessous, sinon
        # violation de contrainte de clé étrangère.
        conn.execute(
            text(
                "DELETE FROM portfolio_snapshots WHERE execution_context_id IN "
                "(SELECT id FROM execution_contexts WHERE label LIKE 'risk-engine-test%')"
            )
        )
        conn.execute(
            text(
                "DELETE FROM positions_snapshots WHERE execution_context_id IN "
                "(SELECT id FROM execution_contexts WHERE label LIKE 'risk-engine-test%')"
            )
        )
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        # `ai_market_agent_strategy` : type_code littéral de la vraie
        # stratégie IA (B12), pas encore seedé par aucun code de production
        # (vérifié par grep) — utilisé ici uniquement pour exercer la
        # branche "protection obligatoire spécifique IA", nettoyé
        # explicitement comme les type_codes de test habituels.
        conn.execute(
            text("DELETE FROM strategy_definitions WHERE type_code LIKE 'risk_engine_test_%' OR type_code = 'ai_market_agent_strategy'")
        )
        conn.execute(
            text(
                "DELETE FROM user_trading_accounts WHERE user_id IN "
                "(SELECT id FROM users WHERE email LIKE 'risk-engine-test-%')"
            )
        )
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'risk-engine-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'risk-engine-test-%'"))
        conn.commit()
    redis_client.delete(Streams.RISK_CRITIQUE_COMPLETED, Streams.RISK_VALIDATION_COMPLETED)
    redis_client.delete(f"{Streams.RISK_CRITIQUE_COMPLETED}.dead-letter")
    redis_client.delete(TRADING_KILL_SWITCH_REDIS_KEY)
    yield
    with _engine.connect() as conn:
        conn.execute(
            text(
                "DELETE FROM portfolio_snapshots WHERE execution_context_id IN "
                "(SELECT id FROM execution_contexts WHERE label LIKE 'risk-engine-test%')"
            )
        )
        conn.execute(
            text(
                "DELETE FROM positions_snapshots WHERE execution_context_id IN "
                "(SELECT id FROM execution_contexts WHERE label LIKE 'risk-engine-test%')"
            )
        )
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM risk_decisions"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(
            text("DELETE FROM strategy_definitions WHERE type_code LIKE 'risk_engine_test_%' OR type_code = 'ai_market_agent_strategy'")
        )
        conn.execute(
            text(
                "DELETE FROM user_trading_accounts WHERE user_id IN "
                "(SELECT id FROM users WHERE email LIKE 'risk-engine-test-%')"
            )
        )
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'risk-engine-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'risk-engine-test-%'"))
        conn.commit()
    redis_client.delete(TRADING_KILL_SWITCH_REDIS_KEY)


def _make_strategy(
    *,
    symbols: list[str] | None = None,
    type_code: str | None = None,
    parameters: dict | None = None,
    status: str = "ACTIVE",
    kind: str = "PAPER",
    execution_context_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> dict:
    """Même principe que `test_risk_critic_agent.py::_make_active_strategy` :
    insère user + execution_context + strategy_definition + strategy
    directement en SQL (ce module n'a pas accès à l'ORM `backend`, image
    Docker séparée). `execution_context_id`/`user_id` : passer ceux d'un
    appel précédent pour faire tenir PLUSIEURS stratégies dans le même
    contexte (nécessaire pour les tests de limite active-count/symboles)."""
    symbols = symbols or ["AAPL"]
    type_code = type_code or f"risk_engine_test_{uuid.uuid4().hex[:8]}"
    parameters = {"stop_loss_pct": 2.0, "take_profit_pct": 4.0} if parameters is None else parameters
    reuse_context = execution_context_id is not None
    def_id, strat_id = (uuid.uuid4() for _ in range(2))
    user_id = user_id or uuid.uuid4()
    ctx_id = execution_context_id or uuid.uuid4()
    with _engine.begin() as conn:
        if not reuse_context:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, display_name, is_active) "
                    "VALUES (:id, :email, 'x', 'Risk Engine Test', true)"
                ),
                {"id": user_id, "email": f"risk-engine-test-{user_id}@zikosofttrader.local"},
            )
            conn.execute(
                text(
                    "INSERT INTO execution_contexts (id, user_id, kind, label, is_active) "
                    "VALUES (:id, :user_id, :kind, 'risk-engine-test', false)"
                ),
                {"id": ctx_id, "user_id": user_id, "kind": kind},
            )
        conn.execute(
            text(
                "INSERT INTO strategy_definitions "
                "(id, type_code, version, manifest, parameter_schema, ui_schema, "
                " defaults_by_profile, required_market_data, is_active) "
                "VALUES (:id, :type_code, '1.0.0', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, "
                " '{}'::jsonb, '{}'::jsonb, true) "
                "ON CONFLICT (type_code) DO NOTHING"
            ),
            {"id": def_id, "type_code": type_code},
        )
        real_def_id = conn.execute(
            text("SELECT id FROM strategy_definitions WHERE type_code = :type_code"), {"type_code": type_code}
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO strategies "
                "(id, user_id, execution_context_id, strategy_definition_id, name, "
                " definition_version, parameters, symbols, risk_configuration, status) "
                "VALUES (:id, :user_id, :ctx_id, :def_id, 'Risk Engine Test Strategy', '1.0.0', "
                " CAST(:parameters AS jsonb), CAST(:symbols AS jsonb), '{}'::jsonb, :status)"
            ),
            {
                "id": strat_id,
                "user_id": user_id,
                "ctx_id": ctx_id,
                "def_id": real_def_id,
                "parameters": json.dumps(parameters),
                "symbols": json.dumps(symbols),
                "status": status,
            },
        )
    return {"user_id": user_id, "execution_context_id": ctx_id, "strategy_id": strat_id}


def _connect_account(*, user_id: uuid.UUID, status: str = "connected") -> None:
    account_id = uuid.uuid4()
    with _engine.begin() as conn:
        provider_id = conn.execute(text("SELECT id FROM trading_providers WHERE code = 'alpaca'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO user_trading_accounts "
                "(id, user_id, trading_provider_id, environment, status, encryption_key_version, "
                " is_default, metadata_json) "
                "VALUES (:id, :user_id, :provider_id, 'paper', :status, 1, true, '{}'::jsonb)"
            ),
            {"id": account_id, "user_id": user_id, "provider_id": provider_id, "status": status},
        )


def _insert_portfolio_and_position_snapshot(
    *, user_id: uuid.UUID, execution_context_id: uuid.UUID, symbol: str
) -> None:
    """§D042/B18 — insère un `portfolio_snapshot`/`positions_snapshot` réels
    (mêmes colonnes que `backend/app/models/portfolio.py`) pour vérifier que
    leur seule PRÉSENCE ne suffit plus à faire taire les constats
    "impossible à vérifier" #11-15 du Risk Engine (voir la correction du
    26/08 dans `workers/risk_engine/main.py` — ces constats sont désormais
    inconditionnels, la vraie cause est l'absence de LIMITE de risque
    configurée, pas l'absence de donnée)."""
    now = datetime.now(UTC)
    with _engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO portfolio_snapshots "
                "(id, user_id, execution_context_id, cash, buying_power, portfolio_value, "
                " daily_pl, total_pl, raw_provider_payload, snapshot_at) "
                "VALUES (:id, :user_id, :ctx_id, 50000.0, 100000.0, 150000.0, "
                " 250.0, 5000.0, '{}'::jsonb, :snapshot_at)"
            ),
            {"id": uuid.uuid4(), "user_id": user_id, "ctx_id": execution_context_id, "snapshot_at": now},
        )
        conn.execute(
            text(
                "INSERT INTO positions_snapshots "
                "(id, user_id, execution_context_id, symbol, quantity, average_entry_price, "
                " market_value, unrealized_pl, snapshot_at) "
                "VALUES (:id, :user_id, :ctx_id, :symbol, 10.0, 150.0, 1550.0, 50.0, :snapshot_at)"
            ),
            {"id": uuid.uuid4(), "user_id": user_id, "ctx_id": execution_context_id, "symbol": symbol, "snapshot_at": now},
        )


def _record_critique(
    *,
    strategy_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    symbol: str,
    market_data_timestamp: str,
    correlation_id: uuid.UUID,
    recommendation: str = "APPROVE",
    confidence: int = 8000,
) -> uuid.UUID:
    """Insère la ligne `agent_decisions` CRITIQUE que le Risk Critic Agent
    (B14) aurait produite — le Risk Engine (B15) la retrouve via
    (strategy_id, reasoning->>'symbol', market_data_timestamp) pour obtenir
    la FK `risk_decisions.agent_decision_id` (NOT NULL)."""
    decision_id = uuid.uuid4()
    with _engine.begin() as conn:
        conn.execute(
            _CRITIQUE_INSERT_SQL,
            {
                "id": decision_id,
                "execution_context_id": execution_context_id,
                "strategy_id": strategy_id,
                "outcome": recommendation,
                "confidence": confidence,
                "reasoning": json.dumps({"text": "critique de test", "symbol": symbol}),
                "risk_flags": json.dumps([]),
                "market_data_timestamp": market_data_timestamp,
                "correlation_id": correlation_id,
            },
        )
    return decision_id


def _publish_critique(
    *,
    execution_context_id: uuid.UUID,
    strategy_id: uuid.UUID,
    symbol: str = "AAPL",
    market_data_timestamp: str,
    correlation_id: uuid.UUID,
    last_close: float | None = 100.0,
    proposal_risk_flags: list[str] | None = None,
    recommendation: str = "APPROVE",
    confidence: int = 8000,
    user_id: uuid.UUID | None = None,
    option_instrument: dict | None = None,
) -> EventEnvelope:
    import redis as redis_module

    client = redis_module.Redis.from_url(os.environ["REDIS_URL"])
    envelope = EventEnvelope(
        event_type="risk.critique.completed",
        correlation_id=correlation_id,
        user_id=user_id,
        execution_context_id=uuid.UUID(str(execution_context_id)),
        payload={
            "strategy_id": str(strategy_id),
            "symbol": symbol,
            "proposed_signal": "BUY",
            "recommendation": recommendation,
            "confidence": confidence,
            "reasoning": "critique de test",
            "risk_flags": [],
            "market_data_timestamp": market_data_timestamp,
            "last_close": last_close,
            "proposal_risk_flags": proposal_risk_flags or [],
            "option_instrument": option_instrument,
        },
    )
    publish_event(client, Streams.RISK_CRITIQUE_COMPLETED, envelope)
    return envelope


def _setup_nominal(*, symbols=None, parameters=None, type_code=None, status="ACTIVE", kind="PAPER", connect=True):
    """Cas nominal réutilisé par la plupart des tests : contexte PAPER,
    compte connecté, stratégie ACTIVE avec stop-loss valide, données
    fraîches, pas de kill switch, pas de cooldown, pas de dépassement de
    limite. Retourne tout ce qu'il faut pour publier/interroger."""
    strat = _make_strategy(symbols=symbols, parameters=parameters, type_code=type_code, status=status, kind=kind)
    if connect:
        _connect_account(user_id=strat["user_id"])
    symbol = (symbols or ["AAPL"])[0]
    ts = datetime.now(UTC).isoformat()
    correlation_id = uuid.uuid4()
    agent_decision_id = _record_critique(
        strategy_id=strat["strategy_id"],
        execution_context_id=strat["execution_context_id"],
        symbol=symbol,
        market_data_timestamp=ts,
        correlation_id=correlation_id,
    )
    return {**strat, "symbol": symbol, "market_data_timestamp": ts, "correlation_id": correlation_id, "agent_decision_id": agent_decision_id}


def _drain(redis_client, stream: str) -> list[dict]:
    entries = redis_client.xrange(stream, min="-", max="+")
    out = []
    for _mid, fields in entries:
        raw = fields.get(b"envelope") or fields.get("envelope")
        if isinstance(raw, bytes):
            raw = raw.decode()
        out.append(json.loads(raw))
    return out


class TestTickEndToEnd:
    def test_nominal_case_best_v1_outcome_is_requires_approval_never_approved(self, engine, redis_client):
        """§B15 "Validation nominale" (P0) — meilleur cas atteignable par
        cette V1 : `REQUIRES_APPROVAL`, jamais `APPROVED` (voir docstring du
        module : 5 contrôles honnêtement "impossible à vérifier" — aucune
        limite de risque configurée nulle part dans le système, voir D042 —
        forcent toujours au moins ce niveau, que des snapshots existent ou
        non)."""
        ctx = _setup_nominal()
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        validations = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)
        assert len(validations) == 1
        payload = validations[0]["payload"]
        assert payload["outcome"] == "REQUIRES_APPROVAL"
        assert any("argent disponible" in r for r in payload["reasons"])
        assert any("notional" in r for r in payload["reasons"])
        assert payload["last_close"] == 100.0  # §B17 — passthrough depuis _publish_critique (défaut 100.0)

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT outcome, agent_decision_id, correlation_id FROM risk_decisions WHERE agent_decision_id = :aid"),
                {"aid": ctx["agent_decision_id"]},
            ).mappings().first()
        assert row is not None
        assert row["outcome"] == "REQUIRES_APPROVAL"
        assert row["correlation_id"] == ctx["correlation_id"]

        # §B28 (D073) — REQUIRES_APPROVAL reste une décision menée à son
        # terme (le Risk Engine A statué), pas un échec : `state` doit être
        # `completed`, pas `rejected`. `agent_type = "risk_engine"`,
        # délibérément distinct de `*_agent` (D029/D073, non-IA).
        with engine.connect() as conn:
            messages = conn.execute(
                text(
                    "SELECT agent_type, state, content FROM agent_messages "
                    "WHERE payload->>'agent_decision_id' = :aid"
                ),
                {"aid": str(ctx["agent_decision_id"])},
            ).mappings().all()
        assert len(messages) == 1
        assert messages[0]["agent_type"] == "risk_engine"
        assert messages[0]["state"] == "completed"
        assert "Validation humaine requise" in messages[0]["content"]

    def test_portfolio_and_position_snapshots_present_still_requires_approval(self, engine, redis_client):
        """§D042 (correction du 26/08) — même avec de VRAIS
        `portfolio_snapshot`/`positions_snapshot` déjà en base pour ce
        contexte/symbole (ce que B18 écrit désormais), le résultat reste
        `REQUIRES_APPROVAL` : la présence de la donnée ne suffit plus à
        faire taire les constats #11-15, seule l'existence d'une LIMITE de
        risque configurée le pourrait — et aucune n'existe en V1. Avant la
        correction, ce scénario aurait fait disparaître 4 des 5 constats
        "impossible à vérifier" en silence."""
        ctx = _setup_nominal()
        _insert_portfolio_and_position_snapshot(
            user_id=ctx["user_id"], execution_context_id=ctx["execution_context_id"], symbol=ctx["symbol"]
        )
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        validations = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)
        assert len(validations) == 1
        payload = validations[0]["payload"]
        assert payload["outcome"] == "REQUIRES_APPROVAL"
        reasons = payload["reasons"]
        assert any("argent disponible" in r and "limite de notional/buying power" in r for r in reasons)
        assert any("perte quotidienne" in r and "limite de perte quotidienne" in r for r in reasons)
        assert any("exposition totale du portefeuille" in r and "limite d'exposition totale" in r for r in reasons)
        assert any(f"exposition sur {ctx['symbol']}" in r and "limite d'exposition par symbole" in r for r in reasons)
        assert any("notional de l'ordre" in r for r in reasons)
        # La donnée existe désormais : le qualificatif "pas de snapshot pour
        # l'instant" ne doit plus apparaître pour ces 4 constats.
        assert not any("pour l'instant" in r for r in reasons)

    def test_rejects_when_kill_switch_engaged(self, engine, redis_client):
        """§B15 "Blocage kill switch" (P0)."""
        set_trading_kill_switch_engaged(redis_client, True)
        ctx = _setup_nominal()
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("kill switch" in r for r in payload["reasons"])

        # §B28 (D073) — REJECTED doit produire `agent_messages.state ==
        # "rejected"`.
        with engine.connect() as conn:
            messages = conn.execute(
                text(
                    "SELECT state FROM agent_messages WHERE payload->>'agent_decision_id' = :aid"
                ),
                {"aid": str(ctx["agent_decision_id"])},
            ).mappings().all()
        assert len(messages) == 1
        assert messages[0]["state"] == "rejected"

    def test_rejects_stale_market_data(self, engine, redis_client):
        """§B15 "Rejet données obsolètes" (P0)."""
        stale_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        strat = _make_strategy()
        _connect_account(user_id=strat["user_id"])
        correlation_id = uuid.uuid4()
        agent_decision_id = _record_critique(
            strategy_id=strat["strategy_id"],
            execution_context_id=strat["execution_context_id"],
            symbol="AAPL",
            market_data_timestamp=stale_ts,
            correlation_id=correlation_id,
        )
        _publish_critique(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            symbol="AAPL",
            market_data_timestamp=stale_ts,
            correlation_id=correlation_id,
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("obsolètes" in r for r in payload["reasons"])
        assert agent_decision_id  # sanity — la FK a bien été utilisée sans lever

    def test_rejects_duplicate_critique_redelivery(self, engine, redis_client):
        """§B15 "Rejet doublon" (P0) — redélivrance du même message
        `risk.critique.completed` (reprise PEL/retry) : une seule décision de
        risque doit être produite, jamais une deuxième pour la même critique."""
        ctx = _setup_nominal()
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        assert len(_drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)) == 1
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM risk_decisions WHERE agent_decision_id = :aid"),
                {"aid": ctx["agent_decision_id"]},
            ).scalar_one()
        assert count == 1

    def test_missing_underlying_critique_decision_is_skipped_not_crashed(self, engine, redis_client):
        """Cas normalement impossible en production (le Risk Critic Agent
        committe toujours `agent_decisions` avant de publier), mais
        `risk_decisions.agent_decision_id` est NOT NULL — aucune décision ne
        doit être fabriquée sans cette FK."""
        strat = _make_strategy()
        ts = datetime.now(UTC).isoformat()
        _publish_critique(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            symbol="AAPL",
            market_data_timestamp=ts,
            correlation_id=uuid.uuid4(),
        )

        risk_engine.tick(engine, redis_client)  # ne doit jamais lever

        assert _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED) == []
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM risk_decisions")).scalar_one()
        assert count == 0

    def test_malformed_payload_is_skipped_not_crashed(self, engine, redis_client):
        import redis as redis_module

        client = redis_module.Redis.from_url(os.environ["REDIS_URL"])
        envelope = EventEnvelope(
            event_type="risk.critique.completed",
            correlation_id=uuid.uuid4(),
            execution_context_id=uuid.uuid4(),
            payload={"recommendation": "APPROVE"},  # symbol/strategy_id/market_data_timestamp manquants
        )
        publish_event(client, Streams.RISK_CRITIQUE_COMPLETED, envelope)

        risk_engine.tick(engine, redis_client)  # ne doit jamais lever

        assert _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED) == []

    def test_rejects_dry_run_execution_context(self, engine, redis_client):
        ctx = _setup_nominal(kind="DRY_RUN", connect=False)
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("DRY_RUN" in r for r in payload["reasons"])

    def test_replay_context_does_not_require_a_trading_account(self, engine, redis_client):
        ctx = _setup_nominal(kind="REPLAY", connect=False)
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert not any("compte de trading" in r for r in payload["reasons"])

    def test_rejects_paper_context_without_connected_account(self, engine, redis_client):
        ctx = _setup_nominal(connect=False)
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("compte de trading" in r for r in payload["reasons"])

    def test_rejects_paper_context_with_pending_account(self, engine, redis_client):
        strat = _make_strategy()
        _connect_account(user_id=strat["user_id"], status="pending")
        ts = datetime.now(UTC).isoformat()
        correlation_id = uuid.uuid4()
        agent_decision_id = _record_critique(
            strategy_id=strat["strategy_id"],
            execution_context_id=strat["execution_context_id"],
            symbol="AAPL",
            market_data_timestamp=ts,
            correlation_id=correlation_id,
        )
        _publish_critique(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            symbol="AAPL",
            market_data_timestamp=ts,
            correlation_id=correlation_id,
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("compte de trading" in r for r in payload["reasons"])
        assert agent_decision_id

    def test_rejects_when_strategy_no_longer_active(self, engine, redis_client):
        ctx = _setup_nominal(status="PAUSED")
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("non ACTIVE" in r for r in payload["reasons"])

    def test_rejects_when_active_strategy_count_exceeds_limit(self, engine, redis_client):
        strat = _make_strategy(symbols=["AAPL"])
        _connect_account(user_id=strat["user_id"])
        for i in range(3):
            _make_strategy(
                symbols=[f"EXTRA{i}"],
                execution_context_id=strat["execution_context_id"],
                user_id=strat["user_id"],
            )
        # 4 stratégies ACTIVE au total dans ce contexte > MAX_ACTIVE_STRATEGIES (3).
        ts = datetime.now(UTC).isoformat()
        correlation_id = uuid.uuid4()
        agent_decision_id = _record_critique(
            strategy_id=strat["strategy_id"],
            execution_context_id=strat["execution_context_id"],
            symbol="AAPL",
            market_data_timestamp=ts,
            correlation_id=correlation_id,
        )
        _publish_critique(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            symbol="AAPL",
            market_data_timestamp=ts,
            correlation_id=correlation_id,
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("stratégies actives" in r for r in payload["reasons"])
        assert agent_decision_id

    def test_rejects_when_cumulative_symbol_count_exceeds_limit(self, engine, redis_client):
        many_symbols = [f"SYM{i}" for i in range(11)]  # > MAX_CUMULATIVE_SYMBOLS (10)
        ctx = _setup_nominal(symbols=many_symbols)
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("symboles cumulés" in r for r in payload["reasons"])

    def test_rejects_deterministic_strategy_without_stop_loss(self, engine, redis_client):
        ctx = _setup_nominal(parameters={"take_profit_pct": 4.0})
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("stop-loss" in r for r in payload["reasons"])

    def test_rejects_ai_strategy_without_require_human_approval(self, engine, redis_client):
        ctx = _setup_nominal(
            type_code="ai_market_agent_strategy",
            parameters={"min_confidence": 7000, "require_human_approval": False},
        )
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REJECTED"
        assert any("approbation humaine" in r for r in payload["reasons"])

    def test_ai_strategy_with_require_human_approval_true_passes_that_check(self, engine, redis_client):
        ctx = _setup_nominal(
            type_code="ai_market_agent_strategy",
            parameters={"min_confidence": 7000, "require_human_approval": True},
        )
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert not any("approbation humaine" in r and "requise" in r for r in payload["reasons"])

    def test_rejects_when_cooldown_still_active(self, engine, redis_client):
        strat = _make_strategy()
        _connect_account(user_id=strat["user_id"])
        ts1 = datetime.now(UTC).isoformat()
        corr1 = uuid.uuid4()
        _record_critique(
            strategy_id=strat["strategy_id"],
            execution_context_id=strat["execution_context_id"],
            symbol="AAPL",
            market_data_timestamp=ts1,
            correlation_id=corr1,
        )
        _publish_critique(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            symbol="AAPL",
            market_data_timestamp=ts1,
            correlation_id=corr1,
        )
        risk_engine.tick(engine, redis_client)  # première décision enregistrée

        ts2 = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
        corr2 = uuid.uuid4()
        _record_critique(
            strategy_id=strat["strategy_id"],
            execution_context_id=strat["execution_context_id"],
            symbol="AAPL",
            market_data_timestamp=ts2,
            correlation_id=corr2,
        )
        _publish_critique(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            symbol="AAPL",
            market_data_timestamp=ts2,
            correlation_id=corr2,
        )
        risk_engine.tick(engine, redis_client)  # quasi immédiat -> cooldown actif

        validations = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)
        assert len(validations) == 2
        assert validations[1]["payload"]["outcome"] == "REJECTED"
        assert any("cooldown" in r for r in validations[1]["payload"]["reasons"])

    def test_requires_approval_when_proposal_flagged_for_human_approval(self, engine, redis_client):
        ctx = _setup_nominal()
        _publish_critique(
            execution_context_id=ctx["execution_context_id"],
            strategy_id=ctx["strategy_id"],
            symbol=ctx["symbol"],
            market_data_timestamp=ctx["market_data_timestamp"],
            correlation_id=ctx["correlation_id"],
            proposal_risk_flags=["requires_human_approval"],
        )

        risk_engine.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.RISK_VALIDATION_COMPLETED)[0]["payload"]
        assert payload["outcome"] == "REQUIRES_APPROVAL"
        assert any("requires_human_approval" in r for r in payload["reasons"])


class TestPureHelpers:
    def test_combine_outcome_no_findings_is_approved(self):
        result = risk_engine._combine_outcome([])
        assert result.outcome == "APPROVED"
        assert result.reasons == []
        assert result.adjustments == {}

    def test_combine_outcome_rejected_wins_over_requires_approval(self):
        result = risk_engine._combine_outcome(
            [(risk_engine.REQUIRES_APPROVAL, "a"), (risk_engine.REJECTED, "b")]
        )
        assert result.outcome == "REJECTED"
        assert result.reasons == ["a", "b"]

    def test_combine_outcome_requires_approval_when_no_rejection(self):
        result = risk_engine._combine_outcome([(risk_engine.REQUIRES_APPROVAL, "x")])
        assert result.outcome == "REQUIRES_APPROVAL"

    def test_combine_outcome_never_produces_adjusted(self):
        """§B15 — limite V1 assumée (voir `shared.risk_decision`) :
        `ADJUSTED` n'existe dans aucun chemin de `_combine_outcome`."""
        result = risk_engine._combine_outcome(
            [(risk_engine.REJECTED, "a"), (risk_engine.REQUIRES_APPROVAL, "b")]
        )
        assert result.outcome != "ADJUSTED"

    def test_parse_iso_timestamp_tolerant(self):
        assert risk_engine._parse_iso_timestamp(None) is None
        assert risk_engine._parse_iso_timestamp("not-a-date") is None
        parsed = risk_engine._parse_iso_timestamp("2025-01-01T00:00:00Z")
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_option_risk_gate_accepts_bounded_replay_instrument(self):
        instrument = {
            "underlying_symbol": "AAPL",
            "symbol": "AAPL260925C00200000",
            "option_type": "call",
            "expiration_date": (date.today() + timedelta(days=14)).isoformat(),
            "strike_price": 200,
            "bid_price": 2.90,
            "ask_price": 3.10,
            "limit_price": 3.10,
            "contract_size": 100,
            "quantity": 1,
            "estimated_premium": 310.0,
            "max_loss": 310.0,
            "spread_pct": 0.066,
        }
        findings = risk_engine._evaluate_option_controls(
            None,
            payload={"symbol": "AAPL", "proposed_signal": "BUY", "option_instrument": instrument},
            strategy={"execution_context_id": uuid.uuid4()},
            execution_context_kind="REPLAY",
        )
        assert findings == []

    def test_option_risk_gate_rejects_expired_and_over_budget_instrument(self):
        instrument = {
            "underlying_symbol": "AAPL",
            "symbol": "AAPL260901P00200000",
            "option_type": "put",
            "expiration_date": (date.today() - timedelta(days=1)).isoformat(),
            "strike_price": 200,
            "bid_price": 6.0,
            "ask_price": 6.5,
            "limit_price": 6.5,
            "contract_size": 100,
            "quantity": 1,
            "estimated_premium": 650.0,
            "max_loss": 650.0,
            "spread_pct": 0.08,
        }
        findings = risk_engine._evaluate_option_controls(
            None,
            payload={"symbol": "AAPL", "proposed_signal": "SELL", "option_instrument": instrument},
            strategy={"execution_context_id": uuid.uuid4()},
            execution_context_kind="REPLAY",
        )
        reasons = [reason for _tier, reason in findings]
        assert any("hors fenêtre" in reason for reason in reasons)
        assert any("prime/perte maximale" in reason for reason in reasons)
