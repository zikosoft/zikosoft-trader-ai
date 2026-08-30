"""B14 — risk_critic_agent/main.py::tick(). Intégration réelle contre
PostgreSQL/Redis (aucun mock d'infra interne) — seule la frontière HTTP
avec l'API Anthropic est mockée (`respx`), même discipline que
`test_ai_provider.py`. Publie `strategy.proposal.created` directement (sans
passer par un vrai Strategy Agent) pour isoler ce qui est propre à B14, même
principe que `test_strategy_agent.py` pour `market.analysis.completed`.

Nécessite `.venv-agents` (le SDK `anthropic` n'est installé que là, voir
`agents/requirements.txt`) — skip proprement sous `.venv` backend, comme
`test_ai_provider.py`."""

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

pytest.importorskip("anthropic", reason="suite agents — lancer avec `make test-agents` (.venv-agents)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

import risk_critic_agent.main as risk_critic_agent  # noqa: E402
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
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(
            text("DELETE FROM strategy_definitions WHERE type_code LIKE 'risk_critic_test_%'")
        )
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'risk-critic-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'risk-critic-test-%'"))
        conn.commit()
    redis_client.delete(Streams.STRATEGY_PROPOSAL_CREATED, Streams.RISK_CRITIQUE_COMPLETED)
    redis_client.delete(f"{Streams.STRATEGY_PROPOSAL_CREATED}.dead-letter")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(
            text("DELETE FROM strategy_definitions WHERE type_code LIKE 'risk_critic_test_%'")
        )
        conn.execute(text("DELETE FROM execution_contexts WHERE label LIKE 'risk-critic-test%'"))
        conn.execute(text("DELETE FROM users WHERE email LIKE 'risk-critic-test-%'"))
        conn.commit()
    os.environ.pop("ANTHROPIC_API_KEY", None)


def _make_active_strategy(
    engine,
    *,
    symbols: list[str],
    type_code: str | None = None,
    execution_context_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> dict:
    """Insère user + execution_context (PAPER) + strategy_definition +
    strategy ACTIVE directement en SQL — ce module n'a pas accès à
    l'ORM/API `backend` (image Docker séparée, même principe que
    `test_market_agent.py`/`test_strategy_agent.py`).

    `execution_context_id`/`user_id` : passer ceux d'un appel précédent pour
    faire tenir DEUX stratégies dans le MÊME contexte d'exécution — c'est ce
    que `_concentration_others` (scoping volontaire par execution_context_id,
    pas juste par user_id : un même utilisateur peut avoir un contexte PAPER
    et un LIVE, dont l'exposition ne doit pas se mélanger) exige pour
    compter plus d'une stratégie ACTIVE exposée au même symbole. Un nouvel
    appel sans ces paramètres crée toujours son propre user+contexte
    isolé, comme avant."""
    type_code = type_code or f"risk_critic_test_{uuid.uuid4().hex[:8]}"
    reuse_context = execution_context_id is not None
    def_id, strat_id = (uuid.uuid4() for _ in range(2))
    user_id = user_id or uuid.uuid4()
    ctx_id = execution_context_id or uuid.uuid4()
    with engine.begin() as conn:
        if not reuse_context:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, display_name, is_active) "
                    "VALUES (:id, :email, 'x', 'Risk Critic Test', true)"
                ),
                {"id": user_id, "email": f"risk-critic-test-{user_id}@zikosofttrader.local"},
            )
            conn.execute(
                text(
                    "INSERT INTO execution_contexts (id, user_id, kind, label, is_active) "
                    "VALUES (:id, :user_id, 'PAPER', 'risk-critic-test', false)"
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
                "VALUES (:id, :user_id, :ctx_id, :def_id, 'Risk Critic Test Strategy', '1.0.0', "
                " '{}'::jsonb, CAST(:symbols AS jsonb), '{}'::jsonb, 'ACTIVE')"
            ),
            {"id": strat_id, "user_id": user_id, "ctx_id": ctx_id, "def_id": def_id, "symbols": json.dumps(symbols)},
        )
    return {"user_id": user_id, "execution_context_id": ctx_id, "strategy_id": strat_id}


def _publish_proposal(
    *,
    execution_context_id,
    strategy_id,
    user_id=None,
    symbol="AAPL",
    signal="BUY",
    confidence=10000,
    reasoning="croisement haussier",
    risk_flags=None,
    market_data_timestamp=None,
    recent_closes=None,
    correlation_id=None,
) -> EventEnvelope:
    import redis as redis_module

    client = redis_module.Redis.from_url(os.environ["REDIS_URL"])
    market_data_timestamp = market_data_timestamp or datetime.now(UTC).isoformat()
    envelope = EventEnvelope(
        event_type="strategy.proposal.created",
        correlation_id=correlation_id or uuid.uuid4(),
        user_id=user_id,
        execution_context_id=uuid.UUID(str(execution_context_id)),
        payload={
            "strategy_id": str(strategy_id),
            "type_code": "risk_critic_test",
            "definition_version": "1.0.0",
            "symbol": symbol,
            "signal": signal,
            "confidence": confidence,
            "reasoning": reasoning,
            "risk_flags": risk_flags or [],
            "market_data_timestamp": market_data_timestamp,
            "window_key": f"{symbol}:{market_data_timestamp}",
            "recent_closes": recent_closes,
        },
    )
    publish_event(client, Streams.STRATEGY_PROPOSAL_CREATED, envelope)
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
    def test_no_api_key_falls_back_to_requires_review(self, engine, redis_client):
        strat = _make_active_strategy(engine, symbols=["AAPL"])
        _publish_proposal(
            execution_context_id=strat["execution_context_id"], strategy_id=strat["strategy_id"], user_id=strat["user_id"]
        )

        risk_critic_agent.tick(engine, redis_client)

        critiques = _drain(redis_client, Streams.RISK_CRITIQUE_COMPLETED)
        assert len(critiques) == 1
        payload = critiques[0]["payload"]
        assert payload["recommendation"] == "REQUIRES_REVIEW"
        assert payload["confidence"] == 0
        assert "ai_unavailable" in payload["risk_flags"]

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT decision_type, outcome, confidence FROM agent_decisions "
                    "WHERE strategy_id = :sid AND decision_type = 'CRITIQUE'"
                ),
                {"sid": strat["strategy_id"]},
            ).mappings().all()
        assert len(rows) == 1
        assert rows[0]["outcome"] == "REQUIRES_REVIEW"

        # §B28 (D073) — REQUIRES_REVIEW reste un avis consultatif mené à son
        # terme, pas un échec : `state` doit être `completed`, pas `rejected`.
        with engine.connect() as conn:
            messages = conn.execute(
                text(
                    "SELECT agent_type, state, content FROM agent_messages "
                    "WHERE payload->>'strategy_id' = CAST(:sid AS text)"
                ),
                {"sid": strat["strategy_id"]},
            ).mappings().all()
        assert len(messages) == 1
        assert messages[0]["agent_type"] == "risk_critic_agent"
        assert messages[0]["state"] == "completed"

    def test_publishes_last_close_and_proposal_risk_flags(self, engine, redis_client):
        """§B15 — régression sur le complément rétroactif de `_record_and_publish` :
        le Risk Engine (premier vrai consommateur) a besoin d'une clôture de
        référence (`last_close`, dernier élément de `recent_closes`) et des
        `risk_flags` de la proposition D'ORIGINE (`proposal_risk_flags`,
        distincts de `risk_flags` qui restent ceux de la CRITIQUE elle-même)."""
        strat = _make_active_strategy(engine, symbols=["AAPL"])
        _publish_proposal(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            risk_flags=["requires_human_approval"],
            recent_closes=[100.0, 101.5, 99.75],
        )

        risk_critic_agent.tick(engine, redis_client)

        critiques = _drain(redis_client, Streams.RISK_CRITIQUE_COMPLETED)
        assert len(critiques) == 1
        payload = critiques[0]["payload"]
        assert payload["last_close"] == 99.75
        assert payload["proposal_risk_flags"] == ["requires_human_approval"]
        # Pas de confusion entre les deux : la critique elle-même (repli
        # sans clé API) a ses propres risk_flags, distincts de ceux de la
        # proposition d'origine forwardés ci-dessus.
        assert payload["risk_flags"] == ["ai_unavailable"]

    def test_last_close_is_none_when_no_recent_closes(self, engine, redis_client):
        """Pas de `recent_closes` dans la proposition (cas légitime, tous les
        appelants ne les fournissent pas nécessairement) -> `last_close` doit
        être `None`, jamais une valeur fabriquée."""
        strat = _make_active_strategy(engine, symbols=["AAPL"])
        _publish_proposal(
            execution_context_id=strat["execution_context_id"],
            strategy_id=strat["strategy_id"],
            recent_closes=None,
        )

        risk_critic_agent.tick(engine, redis_client)

        critiques = _drain(redis_client, Streams.RISK_CRITIQUE_COMPLETED)
        assert critiques[0]["payload"]["last_close"] is None
        assert critiques[0]["payload"]["proposal_risk_flags"] == []

    def test_ai_success_path_via_mocked_anthropic(self, engine, redis_client):
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-test"
        strat = _make_active_strategy(engine, symbols=["AAPL"])
        _publish_proposal(execution_context_id=strat["execution_context_id"], strategy_id=strat["strategy_id"])

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(
                    200,
                    json=_tool_use_response(
                        input_payload={
                            "recommendation": "APPROVE",
                            "confidence": 8000,
                            "reasoning": "concentration faible, données fraîches",
                            "risk_flags": [],
                        }
                    ),
                )
            )
            risk_critic_agent.tick(engine, redis_client)
            # §D022 "tool-use natif, jamais de parsing JSON libre" — vérifié
            # ici comme dans test_ai_provider.py.
            sent_body = mock.calls.last.request.content
        assert b'"tool_choice"' in sent_body

        critiques = _drain(redis_client, Streams.RISK_CRITIQUE_COMPLETED)
        assert len(critiques) == 1
        assert critiques[0]["payload"]["recommendation"] == "APPROVE"
        assert critiques[0]["payload"]["confidence"] == 8000
        assert critiques[0]["payload"]["risk_flags"] == []

    def test_ai_reject_recommendation_produces_rejected_agent_message(self, engine, redis_client):
        """§B28 (D073) — `recommendation == "REJECT"` doit produire
        `agent_messages.state == "rejected"`, seul cas où une CRITIQUE elle-
        même est enregistrée comme un rejet dans le Live Debate."""
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-test"
        strat = _make_active_strategy(engine, symbols=["AAPL"])
        _publish_proposal(
            execution_context_id=strat["execution_context_id"], strategy_id=strat["strategy_id"], user_id=strat["user_id"]
        )

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(
                    200,
                    json=_tool_use_response(
                        input_payload={
                            "recommendation": "REJECT",
                            "confidence": 9000,
                            "reasoning": "concentration excessive sur ce symbole",
                            "risk_flags": ["concentration_high"],
                        }
                    ),
                )
            )
            risk_critic_agent.tick(engine, redis_client)

        critiques = _drain(redis_client, Streams.RISK_CRITIQUE_COMPLETED)
        assert critiques[0]["payload"]["recommendation"] == "REJECT"

        with engine.connect() as conn:
            messages = conn.execute(
                text(
                    "SELECT state, content FROM agent_messages WHERE payload->>'strategy_id' = CAST(:sid AS text)"
                ),
                {"sid": strat["strategy_id"]},
            ).mappings().all()
        assert len(messages) == 1
        assert messages[0]["state"] == "rejected"
        assert "concentration excessive" in messages[0]["content"]

    def test_ai_invalid_output_falls_back_to_requires_review(self, engine, redis_client):
        """Le modèle répond mais avec une valeur hors énumération (au lieu
        d'une erreur réseau) — doit être rattrapé par la revalidation
        Pydantic (D022 défense en profondeur), jamais propagé tel quel."""
        os.environ["ANTHROPIC_API_KEY"] = "fake-key-for-test"
        strat = _make_active_strategy(engine, symbols=["AAPL"])
        _publish_proposal(execution_context_id=strat["execution_context_id"], strategy_id=strat["strategy_id"])

        with respx.mock(assert_all_called=True) as mock:
            mock.post(ANTHROPIC_MESSAGES_URL).mock(
                return_value=httpx.Response(
                    200,
                    json=_tool_use_response(
                        input_payload={"recommendation": "MAYBE", "confidence": 999999, "reasoning": "x"}
                    ),
                )
            )
            risk_critic_agent.tick(engine, redis_client)

        critiques = _drain(redis_client, Streams.RISK_CRITIQUE_COMPLETED)
        assert len(critiques) == 1
        assert critiques[0]["payload"]["recommendation"] == "REQUIRES_REVIEW"
        assert "ai_unavailable" in critiques[0]["payload"]["risk_flags"]

    def test_duplicate_proposal_produces_only_one_critique(self, engine, redis_client):
        strat = _make_active_strategy(engine, symbols=["AAPL"])
        ts = datetime.now(UTC).isoformat()
        _publish_proposal(
            execution_context_id=strat["execution_context_id"], strategy_id=strat["strategy_id"], market_data_timestamp=ts
        )
        _publish_proposal(
            execution_context_id=strat["execution_context_id"], strategy_id=strat["strategy_id"], market_data_timestamp=ts
        )

        risk_critic_agent.tick(engine, redis_client)
        risk_critic_agent.tick(engine, redis_client)

        assert len(_drain(redis_client, Streams.RISK_CRITIQUE_COMPLETED)) == 1
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM agent_decisions WHERE strategy_id = :sid AND decision_type = 'CRITIQUE'"),
                {"sid": strat["strategy_id"]},
            ).scalar_one()
        assert count == 1

    def test_malformed_payload_is_skipped_not_crashed(self, engine, redis_client):
        import redis as redis_module

        client = redis_module.Redis.from_url(os.environ["REDIS_URL"])
        envelope = EventEnvelope(
            event_type="strategy.proposal.created",
            correlation_id=uuid.uuid4(),
            execution_context_id=uuid.uuid4(),
            payload={"signal": "BUY"},  # symbol/strategy_id/market_data_timestamp manquants
        )
        publish_event(client, Streams.STRATEGY_PROPOSAL_CREATED, envelope)

        risk_critic_agent.tick(engine, redis_client)  # ne doit jamais lever

        assert _drain(redis_client, Streams.RISK_CRITIQUE_COMPLETED) == []

    def test_concentration_and_contradiction_are_detected_in_recorded_facts(self, engine, redis_client):
        """§B14 "Examiner concentration"/"contradictions" — deux stratégies
        actives exposées au même symbole, une décision PROPOSAL SELL
        antérieure insérée à la main pour la première, puis une proposition
        BUY publiée pour la seconde : vérifie que les faits enregistrés
        (colonne `reasoning` de la critique) reflètent bien les deux."""
        strat_a = _make_active_strategy(engine, symbols=["AAPL"])
        strat_b = _make_active_strategy(
            engine,
            symbols=["AAPL"],
            execution_context_id=strat_a["execution_context_id"],
            user_id=strat_a["user_id"],
        )
        older_ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        current_ts = datetime.now(UTC).isoformat()

        with engine.begin() as conn:
            conn.execute(
                risk_critic_agent._DECISION_INSERT_SQL,
                {
                    "id": uuid.uuid4(),
                    "execution_context_id": strat_a["execution_context_id"],
                    "strategy_id": strat_a["strategy_id"],
                    "agent_type": "strategy_agent",
                    "decision_type": "PROPOSAL",
                    "outcome": "SELL",
                    "confidence": 10000,
                    "reasoning": json.dumps({"text": "croisement baissier", "symbol": "AAPL", "type_code": "x"}),
                    "risk_flags": json.dumps([]),
                    "market_data_timestamp": older_ts,
                    "correlation_id": uuid.uuid4(),
                },
            )

        _publish_proposal(
            execution_context_id=strat_b["execution_context_id"],
            strategy_id=strat_b["strategy_id"],
            symbol="AAPL",
            signal="BUY",
            market_data_timestamp=current_ts,
            recent_closes=[10.0, 10.5, 9.5, 11.0, 10.2],
        )

        risk_critic_agent.tick(engine, redis_client)

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT reasoning FROM agent_decisions "
                    "WHERE strategy_id = :sid AND decision_type = 'CRITIQUE'"
                ),
                {"sid": strat_b["strategy_id"]},
            ).mappings().one()
        facts = row["reasoning"]["facts"]
        assert facts["concentration_others"] >= 1
        assert facts["contradicts_recent_signal"] is True
        assert "SELL" in facts["recent_contradictory_outcomes"]
        assert facts["volatility_pct"] is not None


class TestPureHelpers:
    def test_volatility_pct_needs_at_least_two_points(self):
        assert risk_critic_agent._volatility_pct([1.0]) is None
        assert risk_critic_agent._volatility_pct([]) is None
        assert risk_critic_agent._volatility_pct(None) is None
        assert risk_critic_agent._volatility_pct("not-a-list") is None

    def test_volatility_pct_computes_high_low_range(self):
        # min=9, max=11, mean=10 -> (11-9)/10*100 = 20%
        assert risk_critic_agent._volatility_pct([10.0, 9.0, 11.0, 10.0]) == pytest.approx(20.0)

    def test_parse_iso_timestamp_tolerant(self):
        assert risk_critic_agent._parse_iso_timestamp("2024-01-01T00:00:00Z") is not None
        assert risk_critic_agent._parse_iso_timestamp("garbage") is None
        assert risk_critic_agent._parse_iso_timestamp(None) is None
        assert risk_critic_agent._parse_iso_timestamp(123) is None

    def test_fallback_critique_is_conservative(self):
        critique = risk_critic_agent._fallback_critique("timeout")
        assert critique.recommendation == "REQUIRES_REVIEW"
        assert critique.confidence == 0
        assert "ai_unavailable" in critique.risk_flags

    def test_critique_with_ai_none_provider_returns_fallback(self):
        critique = risk_critic_agent._critique_with_ai({}, None)
        assert critique.recommendation == "REQUIRES_REVIEW"
        assert "ai_unavailable" in critique.risk_flags
