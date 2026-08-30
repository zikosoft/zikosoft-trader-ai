"""B16 — agents/execution_explanation_agent/main.py::tick(). Intégration
réelle contre PostgreSQL/Redis (aucun mock d'infra interne) — seule la
frontière HTTP avec l'API Anthropic est mockée (`respx`), même discipline
que `test_risk_critic_agent.py`. Publie `risk.validation.completed`
directement (sans passer par un vrai Risk Engine) après avoir inséré la
ligne `agent_decisions` CRITIQUE sous-jacente à la main — même principe que
`test_risk_engine.py` pour `risk.critique.completed`.

**Le scénario `APPROVED` est construit directement dans les tests** (jamais
produit par le vrai B15 tant que B17/B18 n'existent pas, voir D033/R17) —
c'est la seule façon d'exercer honnêtement le chemin "préparer une commande
d'ordre" avant que ces bricks n'arrivent.

Nécessite `.venv-agents` (le SDK `anthropic` n'est installé que là) — skip
proprement sous `.venv` backend, comme `test_risk_critic_agent.py`."""

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

pytest.importorskip("anthropic", reason="suite agents — lancer avec `make test-agents` (.venv-agents)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

import execution_explanation_agent.main as execution_explanation_agent  # noqa: E402
from sqlalchemy import text  # noqa: E402

from shared.eventbus import publish_event  # noqa: E402
from shared.events import EventEnvelope, Streams  # noqa: E402

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _tool_use_response(*, input_payload: dict) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [{"type": "tool_use", "id": "toolu_test", "name": "emit_structured_output", "input": input_payload}],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


@pytest.fixture()
def engine():
    from app.db import engine as _engine  # noqa: PLC0415 — après importorskip/sys.path, volontaire

    return _engine


@pytest.fixture(autouse=True)
def _clean_state(engine, redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code LIKE 'explanation_test_%'"))
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'explanation-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'explanation-test-%'"))
        conn.commit()
    redis_client.delete(Streams.RISK_VALIDATION_COMPLETED, Streams.SYSTEM_EVENTS, Streams.ORDER_COMMANDS)
    redis_client.delete(f"{Streams.RISK_VALIDATION_COMPLETED}.dead-letter")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code LIKE 'explanation_test_%'"))
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'explanation-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'explanation-test-%'"))
        conn.commit()
    os.environ.pop("ANTHROPIC_API_KEY", None)


def _make_strategy(engine, *, parameters=None, type_code=None) -> dict:
    type_code = type_code or f"explanation_test_{uuid.uuid4().hex[:8]}"
    parameters = {"stop_loss_pct": 2.0, "take_profit_pct": 4.0} if parameters is None else parameters
    def_id, strat_id = (uuid.uuid4() for _ in range(2))
    user_id = uuid.uuid4()
    ctx_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, 'x', 'Explanation Test', true)"
            ),
            {"id": user_id, "email": f"explanation-test-{user_id}@zikosofttrader.local"},
        )
        conn.execute(
            text(
                "INSERT INTO execution_contexts (id, user_id, kind, label, is_active) "
                "VALUES (:id, :user_id, 'PAPER', 'explanation-test', false)"
            ),
            {"id": ctx_id, "user_id": user_id},
        )
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
                "VALUES (:id, :user_id, :ctx_id, :def_id, 'Explanation Test Strategy', '1.0.0', "
                " CAST(:parameters AS jsonb), CAST(:symbols AS jsonb), '{}'::jsonb, 'ACTIVE')"
            ),
            {
                "id": strat_id,
                "user_id": user_id,
                "ctx_id": ctx_id,
                "def_id": def_id,
                "parameters": json.dumps(parameters),
                "symbols": json.dumps(["AAPL"]),
            },
        )
    return {"user_id": user_id, "execution_context_id": ctx_id, "strategy_id": strat_id}


def _insert_critique(
    engine,
    *,
    strategy_id,
    execution_context_id,
    symbol="AAPL",
    proposed_signal="BUY",
    recommendation="APPROVE",
    confidence=8000,
    reasoning_text="critique de test",
    market_data_timestamp=None,
) -> uuid.UUID:
    decision_id = uuid.uuid4()
    market_data_timestamp = market_data_timestamp or datetime.now(UTC).isoformat()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_decisions "
                "(id, execution_context_id, strategy_id, agent_type, decision_type, outcome, confidence, "
                " reasoning, risk_flags, market_data_timestamp, correlation_id) "
                "VALUES (:id, :execution_context_id, :strategy_id, 'risk_critic_agent', 'CRITIQUE', :outcome, "
                " :confidence, CAST(:reasoning AS jsonb), '[]'::jsonb, :market_data_timestamp, :correlation_id)"
            ),
            {
                "id": decision_id,
                "execution_context_id": execution_context_id,
                "strategy_id": strategy_id,
                "outcome": recommendation,
                "confidence": confidence,
                "reasoning": json.dumps({"text": reasoning_text, "symbol": symbol, "proposed_signal": proposed_signal}),
                "market_data_timestamp": market_data_timestamp,
                "correlation_id": uuid.uuid4(),
            },
        )
    return decision_id


def _publish_validation(
    *,
    execution_context_id,
    strategy_id,
    agent_decision_id,
    risk_decision_id=None,
    symbol="AAPL",
    outcome="REJECTED",
    reasons=None,
    adjustments=None,
    correlation_id=None,
    last_close=100.0,
) -> EventEnvelope:
    import redis as redis_module

    client = redis_module.Redis.from_url(os.environ["REDIS_URL"])
    risk_decision_id = risk_decision_id or uuid.uuid4()
    envelope = EventEnvelope(
        event_type="risk.validation.completed",
        correlation_id=correlation_id or uuid.uuid4(),
        execution_context_id=uuid.UUID(str(execution_context_id)),
        payload={
            "risk_decision_id": str(risk_decision_id),
            "agent_decision_id": str(agent_decision_id),
            "strategy_id": str(strategy_id),
            "symbol": symbol,
            "outcome": outcome,
            "reasons": reasons if reasons is not None else ["données de marché obsolètes"],
            "adjustments": adjustments or {},
            "last_close": last_close,
        },
    )
    publish_event(client, Streams.RISK_VALIDATION_COMPLETED, envelope)
    return envelope


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
    def test_no_api_key_falls_back_to_template_and_no_order_command(self, engine, redis_client):
        strat = _make_strategy(engine)
        aid = _insert_critique(engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"])
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            outcome="REJECTED",
            reasons=["données de marché obsolètes"],
        )

        execution_explanation_agent.tick(engine, redis_client)

        events = _drain(redis_client, Streams.SYSTEM_EVENTS)
        assert len(events) == 1
        payload = events[0]["payload"]
        assert "refusée" in payload["novice_summary"]
        assert "obsolètes" in payload["expert_summary"]
        assert _drain(redis_client, Streams.ORDER_COMMANDS) == []

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT outcome, reasoning FROM agent_decisions WHERE decision_type = 'EXPLANATION'")
            ).mappings().first()
        assert row is not None
        assert row["outcome"] == "REJECTED"
        assert row["reasoning"]["source"] == "template"

        with engine.connect() as conn:
            msg = conn.execute(text("SELECT state, content FROM agent_messages")).mappings().first()
        assert msg is not None
        assert msg["state"] == "rejected"
        assert "refusée" in msg["content"]

    def test_ai_success_path_via_mocked_anthropic(self, engine, redis_client):
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-test"
        strat = _make_strategy(engine)
        aid = _insert_critique(engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"])
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            outcome="REQUIRES_APPROVAL",
        )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(
                    200,
                    json=_tool_use_response(
                        input_payload={
                            "novice_summary": "Un humain doit valider cette proposition avant de continuer.",
                            "expert_summary": "REQUIRES_APPROVAL : données jugées obsolètes par le Risk Engine.",
                        }
                    ),
                )
            )
            execution_explanation_agent.tick(engine, redis_client)
            sent_body = mock.calls.last.request.content
        assert b'"tool_choice"' in sent_body

        events = _drain(redis_client, Streams.SYSTEM_EVENTS)
        assert events[0]["payload"]["novice_summary"] == "Un humain doit valider cette proposition avant de continuer."
        with engine.connect() as conn:
            row = conn.execute(text("SELECT reasoning FROM agent_decisions WHERE decision_type = 'EXPLANATION'")).mappings().first()
        assert row["reasoning"]["source"] == "ai"

    def test_ai_invalid_output_falls_back_to_template(self, engine, redis_client):
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-test"
        strat = _make_strategy(engine)
        aid = _insert_critique(engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"])
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            outcome="REJECTED",
        )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(200, json=_tool_use_response(input_payload={"novice_summary": ""}))
            )
            execution_explanation_agent.tick(engine, redis_client)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT reasoning FROM agent_decisions WHERE decision_type = 'EXPLANATION'")).mappings().first()
        assert row["reasoning"]["source"] == "template"

    def test_approved_outcome_with_buy_signal_publishes_order_command(self, engine, redis_client):
        """Scénario `APPROVED` construit directement (jamais produit par le
        vrai B15 tant que B17/B18 manquent, voir D033/R17) — seule façon
        honnête d'exercer ce chemin avant que ces bricks n'existent."""
        strat = _make_strategy(engine, parameters={"stop_loss_pct": 3.0, "take_profit_pct": 6.0})
        aid = _insert_critique(
            engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"], proposed_signal="BUY"
        )
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            outcome="APPROVED",
            reasons=[],
            last_close=142.5,
        )

        execution_explanation_agent.tick(engine, redis_client)

        commands = _drain(redis_client, Streams.ORDER_COMMANDS)
        assert len(commands) == 1
        payload = commands[0]["payload"]
        assert payload["side"] == "buy"
        assert payload["symbol"] == "AAPL"
        assert payload["stop_loss_pct"] == 3.0
        assert payload["take_profit_pct"] == 6.0
        assert payload["reference_price"] == 142.5
        assert payload["notional"] is None
        assert payload["quantity"] is None
        assert payload["sizing_pending"] is True

    def test_approved_outcome_with_sell_signal_publishes_sell_command(self, engine, redis_client):
        strat = _make_strategy(engine)
        aid = _insert_critique(
            engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"], proposed_signal="SELL"
        )
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            outcome="APPROVED",
            reasons=[],
        )

        execution_explanation_agent.tick(engine, redis_client)

        commands = _drain(redis_client, Streams.ORDER_COMMANDS)
        assert commands[0]["payload"]["side"] == "sell"

    def test_approved_outcome_with_hold_signal_does_not_publish_order_command(self, engine, redis_client):
        strat = _make_strategy(engine)
        aid = _insert_critique(
            engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"], proposed_signal="HOLD"
        )
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            outcome="APPROVED",
            reasons=[],
        )

        execution_explanation_agent.tick(engine, redis_client)

        assert _drain(redis_client, Streams.ORDER_COMMANDS) == []

    def test_rejected_outcome_never_publishes_order_command(self, engine, redis_client):
        strat = _make_strategy(engine)
        aid = _insert_critique(engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"])
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            outcome="REJECTED",
        )

        execution_explanation_agent.tick(engine, redis_client)

        assert _drain(redis_client, Streams.ORDER_COMMANDS) == []

    def test_duplicate_risk_decision_produces_only_one_explanation(self, engine, redis_client):
        strat = _make_strategy(engine)
        aid = _insert_critique(engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"])
        risk_decision_id = uuid.uuid4()
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            risk_decision_id=risk_decision_id,
        )
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=aid,
            risk_decision_id=risk_decision_id,
        )

        execution_explanation_agent.tick(engine, redis_client)

        assert len(_drain(redis_client, Streams.SYSTEM_EVENTS)) == 1
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM agent_decisions WHERE decision_type = 'EXPLANATION'")).scalar_one()
        assert count == 1

    def test_malformed_payload_is_skipped_not_crashed(self, engine, redis_client):
        import redis as redis_module

        client = redis_module.Redis.from_url(os.environ["REDIS_URL"])
        envelope = EventEnvelope(
            event_type="risk.validation.completed",
            correlation_id=uuid.uuid4(),
            execution_context_id=uuid.uuid4(),
            payload={"outcome": "REJECTED"},  # risk_decision_id/agent_decision_id/strategy_id manquants
        )
        publish_event(client, Streams.RISK_VALIDATION_COMPLETED, envelope)

        execution_explanation_agent.tick(engine, redis_client)  # ne doit jamais lever

        assert _drain(redis_client, Streams.SYSTEM_EVENTS) == []

    def test_missing_critique_is_skipped_not_crashed(self, engine, redis_client):
        strat = _make_strategy(engine)
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            agent_decision_id=uuid.uuid4(),  # n'existe pas
        )

        execution_explanation_agent.tick(engine, redis_client)  # ne doit jamais lever

        assert _drain(redis_client, Streams.SYSTEM_EVENTS) == []

    def test_missing_strategy_is_skipped_not_crashed(self, engine, redis_client):
        strat = _make_strategy(engine)
        aid = _insert_critique(engine, strategy_id=strat["strategy_id"], execution_context_id=strat["execution_context_id"])
        _publish_validation(
            execution_context_id=strat["execution_context_id"],
            strategy_id=uuid.uuid4(),  # n'existe pas
            agent_decision_id=aid,
        )

        execution_explanation_agent.tick(engine, redis_client)  # ne doit jamais lever

        assert _drain(redis_client, Streams.SYSTEM_EVENTS) == []


class TestPureHelpers:
    def test_fallback_explanation_mentions_outcome_and_first_reason(self):
        explanation = execution_explanation_agent._fallback_explanation(
            outcome="REJECTED", reasons=["cooldown actif", "autre raison"]
        )
        assert "refusée" in explanation.novice_summary
        assert "cooldown actif" in explanation.novice_summary
        assert "cooldown actif" in explanation.expert_summary
        assert "autre raison" in explanation.expert_summary

    def test_fallback_explanation_handles_no_reasons(self):
        explanation = execution_explanation_agent._fallback_explanation(outcome="REQUIRES_APPROVAL", reasons=[])
        assert "approbation humaine" in explanation.novice_summary
        assert "nominaux" in explanation.expert_summary

    def test_build_order_command_payload_never_fabricates_sizing(self):
        strategy = {
            "strategy_id": uuid.uuid4(),
            "parameters": {"stop_loss_pct": 1.5, "take_profit_pct": 3.0},
        }
        payload = execution_explanation_agent._build_order_command_payload(
            strategy=strategy,
            symbol="AAPL",
            proposed_signal="BUY",
            risk_decision_id=uuid.uuid4(),
            agent_decision_id=uuid.uuid4(),
            explanation_id=uuid.uuid4(),
            adjustments={},
            reference_price=150.0,
        )
        assert payload["reference_price"] == 150.0
        assert payload["notional"] is None
        assert payload["quantity"] is None
        assert payload["sizing_pending"] is True
        assert payload["side"] == "buy"
        assert payload["stop_loss_pct"] == 1.5
