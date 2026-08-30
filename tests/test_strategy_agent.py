"""B13 — strategy_agent/main.py::tick(). Intégration réelle contre
PostgreSQL/Redis (aucun mock d'infra interne, seulement le pipeline
market.analysis.completed -> strategy.proposal.created, publié à la main
ici pour ne pas dépendre d'un vrai réseau Alpaca — même limite documentée
que test_market_agent.py). Utilise la vraie stratégie
`moving_average_crossover` (B12) synchronisée par le registre B11, pas une
définition injectée artificiellement.

Ne nécessite PAS `.venv-agents` (ce module n'ouvre aucune session MCP,
contrairement à market_agent — voir docstring de
`agents/strategy_agent/main.py`) : tourne sous le venv backend standard."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest
import redis as redis_module
from app.config import settings
from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))

import strategy_agent.main as strategy_agent  # noqa: E402

from shared.eventbus import publish_event  # noqa: E402
from shared.events import EventEnvelope, Streams  # noqa: E402
from shared.risk_governance import set_trading_kill_switch_engaged  # noqa: E402

VALID_PARAMS = {
    "timeframe": "1Day",
    "short_period": 3,
    "long_period": 10,
    "stop_loss_pct": 2.0,
    "take_profit_pct": 4.0,
}

# §B13 — construits pour que le croisement se produise exactement sur la
# dernière bougie (voir strategies/moving_average_crossover/engine.py) :
# plat pendant 12 bougies (SMA3 == SMA10 == 10, pas de croisement) puis un
# saut sur la 13e -> SMA3 franchit SMA10 à la hausse -> BUY univoque.
_CROSSING_CLOSES = [10.0] * 12 + [50.0]
_FLAT_CLOSES = [10.0] * 13


def _bars(closes: list[float]) -> list[dict]:
    return [
        {"timestamp": f"2026-01-{i + 1:02d}T00:00:00Z", "close": close, "open": None, "high": None, "low": None, "volume": None}
        for i, close in enumerate(closes)
    ]


@pytest.fixture(autouse=True)
def _clean_state(redis_client):
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code = 'strategy_agent_test_unsupported_stub'"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()
    # flushdb (pas seulement les streams utilisés ici) : la connexion/login
    # (B05) applique un rate-limit garder en Redis — sans purge complète, des
    # tests consécutifs qui se logguent chacun via `paper_client` finissent
    # par déclencher un 429 (constaté en exécutant cette suite), même
    # principe que `test_strategy_instances_api.py::_clean_state`.
    redis_client.flushdb()
    yield
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM agent_messages"))
        conn.execute(text("DELETE FROM agent_decisions"))
        conn.execute(text("DELETE FROM strategy_runs"))
        conn.execute(text("DELETE FROM strategies"))
        conn.execute(text("DELETE FROM strategy_definitions WHERE type_code = 'strategy_agent_test_unsupported_stub'"))
        conn.execute(text("DELETE FROM execution_context_switches"))
        conn.execute(text("UPDATE execution_contexts SET is_active = false"))
        conn.commit()


@pytest.fixture()
def paper_client():
    with TestClient(app) as c:  # déclenche le lifespan -> sync réelle de strategies/
        response = c.post(
            "/api/auth/login",
            json={"email": settings.demo_user_email, "password": settings.demo_user_password},
        )
        assert response.status_code == 200
        response = c.post("/api/contexts/select", json={"kind": "PAPER"})
        assert response.status_code == 200
        yield c


def _create_active_instance(client, **overrides) -> dict:
    payload = {
        "type_code": "moving_average_crossover",
        "name": "Strategy Agent test",
        "symbols": ["AAPL"],
        "parameters": VALID_PARAMS,
    }
    payload.update(overrides)
    response = client.post("/api/strategies/instances", json=payload)
    assert response.status_code == 201, response.text
    instance = response.json()
    response = client.post(f"/api/strategies/instances/{instance['id']}/activate")
    assert response.status_code == 200, response.text
    return response.json()


def _publish_analysis(*, execution_context_id, evidence: dict, stale: bool = False, user_id=None) -> EventEnvelope:
    client = redis_module.Redis.from_url(os.environ["REDIS_URL"])
    envelope = EventEnvelope(
        event_type="market.analysis.completed",
        correlation_id=uuid.uuid4(),
        user_id=user_id,
        execution_context_id=uuid.UUID(str(execution_context_id)),
        payload={"evidence": evidence, "stale": stale, "account_id": str(uuid.uuid4()), "watchlist": ["AAPL"]},
    )
    publish_event(client, Streams.MARKET_ANALYSIS_COMPLETED, envelope)
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
    def test_active_strategy_with_crossing_bars_produces_buy_proposal(self, paper_client, redis_client):
        instance = _create_active_instance(paper_client)
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)

        proposals = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)
        assert len(proposals) == 1
        payload = proposals[0]["payload"]
        assert payload["strategy_id"] == instance["id"]
        assert payload["symbol"] == "AAPL"
        assert payload["signal"] == "BUY"
        assert payload["confidence"] == 10000
        assert "franchit" in payload["reasoning"]

        with engine.connect() as conn:
            runs = conn.execute(
                text("SELECT outcome, confidence, window_key FROM strategy_runs WHERE strategy_id = :sid"),
                {"sid": instance["id"]},
            ).mappings().all()
            decisions = conn.execute(
                text(
                    "SELECT decision_type, outcome, confidence, reasoning, risk_flags, correlation_id "
                    "FROM agent_decisions WHERE strategy_id = :sid"
                ),
                {"sid": instance["id"]},
            ).mappings().all()
        assert len(runs) == 1
        assert runs[0]["outcome"] == "BUY"
        assert runs[0]["confidence"] == 10000
        assert runs[0]["window_key"] == "AAPL:2026-01-13T00:00:00+00:00"

        assert len(decisions) == 1
        assert decisions[0]["decision_type"] == "PROPOSAL"
        assert decisions[0]["outcome"] == "BUY"
        assert decisions[0]["risk_flags"] == []
        assert decisions[0]["reasoning"]["symbol"] == "AAPL"

        # §B28 (D073) — la proposition écrit AUSSI une ligne `agent_messages`
        # (Live Debate), même transaction que `agent_decisions` ci-dessus.
        with engine.connect() as conn:
            messages = conn.execute(
                text(
                    "SELECT agent_type, state, content, payload, conversation_thread_id "
                    "FROM agent_messages WHERE payload->>'strategy_id' = :sid"
                ),
                {"sid": str(instance["id"])},
            ).mappings().all()
        assert len(messages) == 1
        assert messages[0]["agent_type"] == "strategy_agent"
        assert messages[0]["state"] == "completed"
        assert "franchit" in messages[0]["content"]
        assert messages[0]["payload"]["outcome"] == "BUY"
        assert messages[0]["payload"]["symbol"] == "AAPL"
        assert messages[0]["payload"]["decision_type"] == "PROPOSAL"

    def test_kill_switch_engaged_blocks_evaluation_entirely(self, paper_client, redis_client):
        """§B31 "Bloquer nouvelles propositions exécutables" — aucune
        stratégie évaluée, aucune proposition publiée, aucun appel IA."""
        instance = _create_active_instance(paper_client)
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)
        set_trading_kill_switch_engaged(redis_client, True)

        strategy_agent.tick(engine, redis_client)

        assert _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED) == []
        with engine.connect() as conn:
            decisions = conn.execute(
                text("SELECT id FROM agent_decisions WHERE strategy_id = :sid"), {"sid": instance["id"]}
            ).mappings().all()
        assert decisions == []

    def test_flat_bars_produce_hold_with_zero_confidence(self, paper_client, redis_client):
        instance = _create_active_instance(paper_client)
        evidence = {"bars": {"AAPL": {"1Day": _bars(_FLAT_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)

        proposals = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)
        assert len(proposals) == 1
        assert proposals[0]["payload"]["signal"] == "HOLD"
        assert proposals[0]["payload"]["confidence"] == 0

    def test_same_candle_never_produces_two_proposals(self, paper_client, redis_client):
        """§B13 critère d'acceptation central : "une même bougie ne produit
        pas deux propositions identiques" — publie DEUX événements distincts
        (deux ticks Market Agent différents, deux message_id Redis
        différents) portant la MÊME dernière bougie -> un seul
        `strategy_runs`/`agent_decisions`/`strategy.proposal.created`."""
        instance = _create_active_instance(paper_client)
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)
        strategy_agent.tick(engine, redis_client)

        proposals = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)
        assert len(proposals) == 1

        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM strategy_runs WHERE strategy_id = :sid"), {"sid": instance["id"]}
            ).scalar_one()
        assert count == 1

        # §B28 (D073) — le même verrou anti-doublon protège `agent_messages`
        # (écrit dans la même transaction que `strategy_runs`/`agent_decisions`,
        # jamais atteint si `ON CONFLICT DO NOTHING` a déjà retourné `None`).
        with engine.connect() as conn:
            message_count = conn.execute(
                text("SELECT count(*) FROM agent_messages WHERE payload->>'strategy_id' = :sid"),
                {"sid": str(instance["id"])},
            ).scalar_one()
        assert message_count == 1

    def test_stale_data_is_refused_without_evaluating_anything(self, paper_client, redis_client):
        instance = _create_active_instance(paper_client)
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence, stale=True)

        strategy_agent.tick(engine, redis_client)

        assert _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED) == []
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM strategy_runs WHERE strategy_id = :sid"), {"sid": instance["id"]}
            ).scalar_one()
        assert count == 0

    def test_missing_bars_for_symbol_is_skipped_not_crashed(self, paper_client, redis_client):
        instance = _create_active_instance(paper_client)
        evidence = {"bars": {}}  # aucune bougie collectée pour AAPL
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)  # ne doit jamais lever

        assert _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED) == []

    def test_no_active_strategy_is_a_silent_noop(self, redis_client):
        _publish_analysis(execution_context_id=uuid.uuid4(), evidence={"bars": {}})
        strategy_agent.tick(engine, redis_client)  # ne doit jamais lever
        assert _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED) == []

    def test_unsupported_capability_strategy_is_skipped_deterministic_sibling_still_runs(self, paper_client, redis_client):
        """§D017 — depuis B12 "AI Market Agent Strategy", `["ai"]` seul EST
        supporté (voir `TestAiMarketAgentStrategyEndToEnd` plus bas) : ce
        test couvre désormais le cas d'une capacité GENUINEMENT non prise en
        charge (simulée via une ligne insérée directement en base, même
        contournement que les fixtures `test_market_agent.py` qui insèrent
        en SQL brut plutôt que de dépendre d'une vraie API tierce) pour
        prouver que la branche de saut (§ manifest.required_capabilities)
        reste réellement exécutée pour tout ce qui n'est pas exactement
        `["ai"]`, pas seulement plausible."""
        deterministic = _create_active_instance(paper_client)

        definition_id = uuid.uuid4()
        unsupported_strategy_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO strategy_definitions "
                    "(id, type_code, version, manifest, parameter_schema, ui_schema, "
                    " defaults_by_profile, required_market_data, is_active) "
                    "VALUES (:id, 'strategy_agent_test_unsupported_stub', '1.0.0', "
                    " CAST(:manifest AS jsonb), CAST(:ps AS jsonb), CAST(:us AS jsonb), "
                    " CAST(:dbp AS jsonb), CAST(:rmd AS jsonb), true)"
                ),
                {
                    "id": definition_id,
                    "manifest": '{"required_capabilities": ["some_future_capability_not_supported_yet"]}',
                    "ps": "{}",
                    "us": "{}",
                    "dbp": "{}",
                    "rmd": "{}",
                },
            )
            conn.execute(
                text(
                    "INSERT INTO strategies "
                    "(id, user_id, execution_context_id, strategy_definition_id, name, "
                    " definition_version, parameters, symbols, risk_configuration, status) "
                    "SELECT :id, s.user_id, s.execution_context_id, :def_id, 'Unsupported capability stub', '1.0.0', "
                    "       '{}'::jsonb, '[\"AAPL\"]'::jsonb, '{}'::jsonb, 'ACTIVE' "
                    "FROM strategies s WHERE s.id = :sibling_id"
                ),
                {"id": unsupported_strategy_id, "def_id": definition_id, "sibling_id": deterministic["id"]},
            )

        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=deterministic["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)  # ne doit jamais lever sur la stratégie non supportée

        proposals = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)
        # Seule la stratégie déterministe produit une proposition — la
        # capacité non supportée est ignorée proprement (§D017).
        assert len(proposals) == 1
        assert proposals[0]["payload"]["strategy_id"] == deterministic["id"]
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM strategy_runs WHERE strategy_id = :sid"), {"sid": unsupported_strategy_id}
            ).scalar_one()
        assert count == 0


class _FakeAIProvider:
    """Double duck-typé de `shared.ai_provider.AIProvider` — n'implémente
    QUE `structured_complete()`, jamais `import anthropic` (contrairement à
    `ClaudeAIProvider._call_structured`, déjà testé isolément dans
    `test_ai_provider.py` sous `.venv-agents`). Permet de tester le chemin
    IA complet du Strategy Agent (B12 "AI Market Agent Strategy") sous le
    venv backend standard, sans dépendance au SDK `anthropic` ni à
    `respx` — `agents/strategy_agent/main.py` n'appelle jamais le SDK
    directement, seulement l'interface abstraite `AIProvider`."""

    def __init__(self, *, result: dict | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict] = []

    def structured_complete(self, *, prompt, schema, tier, context_label=""):
        self.calls.append({"prompt": prompt, "schema": schema, "tier": tier, "context_label": context_label})
        if self._error is not None:
            raise self._error
        return self._result


AI_VALID_PARAMS = {
    "timeframe": "1Day",
    "analysis_frequency": "1Day",
    "risk_posture": "balanced",
    "min_confidence": 5000,
    "max_notional_usd": 1000.0,
    "require_human_approval": True,
}


class TestAiMarketAgentStrategyEndToEnd:
    """§B12 "AI Market Agent Strategy" — premier exercice réel du chemin IA
    du Strategy Agent (la branche `required_capabilities == ["ai"]` était
    jusqu'ici seulement couverte par le cas "capacité non supportée", voir
    `TestTickEndToEnd.test_unsupported_capability_strategy_is_skipped_deterministic_sibling_still_runs`
    ci-dessus, avant B12). `strategy_agent._build_ai_provider` est
    monkeypatché pour injecter `_FakeAIProvider` — la construction réelle
    d'un `AIProvider` (clé API, interrupteur D026) reste couverte par
    `TestPureHelpers`/`test_ai_provider.py`."""

    def test_ai_strategy_signal_and_confidence_survive_to_agent_decisions(self, paper_client, redis_client, monkeypatch):
        fake = _FakeAIProvider(
            result={"signal": "BUY", "confidence": 8500, "reasoning": "tendance haussière nette", "risk_flags": []}
        )
        monkeypatch.setattr(strategy_agent, "_build_ai_provider", lambda _redis: fake)

        instance = _create_active_instance(
            paper_client, type_code="ai_market_agent_strategy", parameters=AI_VALID_PARAMS
        )
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)

        assert len(fake.calls) == 1  # un seul symbole, un seul appel IA

        proposals = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)
        assert len(proposals) == 1
        payload = proposals[0]["payload"]
        assert payload["signal"] == "BUY"
        # Confiance IA propagée telle quelle — PAS la convention 10000/0 des
        # stratégies déterministes (trou d'architecture corrigé en B12,
        # voir docstring de `_build_proposal`).
        assert payload["confidence"] == 8500
        # §B12 "Validation humaine configurable" (AI_VALID_PARAMS a
        # require_human_approval=True) — signal non-HOLD -> flag présent.
        assert "requires_human_approval" in payload["risk_flags"]

        with engine.connect() as conn:
            decision = conn.execute(
                text("SELECT confidence, risk_flags FROM agent_decisions WHERE strategy_id = :sid"),
                {"sid": instance["id"]},
            ).mappings().one()
        assert decision["confidence"] == 8500
        assert "requires_human_approval" in decision["risk_flags"]

    def test_low_ai_confidence_is_downgraded_to_hold(self, paper_client, redis_client, monkeypatch):
        # AI_VALID_PARAMS.min_confidence = 5000 ; l'IA renvoie 2000 -> protection.
        fake = _FakeAIProvider(
            result={"signal": "SELL", "confidence": 2000, "reasoning": "signal faible", "risk_flags": []}
        )
        monkeypatch.setattr(strategy_agent, "_build_ai_provider", lambda _redis: fake)

        instance = _create_active_instance(
            paper_client, type_code="ai_market_agent_strategy", parameters=AI_VALID_PARAMS
        )
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)[0]["payload"]
        assert payload["signal"] == "HOLD"
        assert "below_min_confidence" in payload["risk_flags"]
        # Rétrogradé en HOLD -> jamais marqué "requires_human_approval"
        # (protection réservée aux signaux non-HOLD réellement proposés).
        assert "requires_human_approval" not in payload["risk_flags"]

    def test_ai_unavailable_produces_conservative_hold(self, paper_client, redis_client, monkeypatch):
        monkeypatch.setattr(strategy_agent, "_build_ai_provider", lambda _redis: None)

        instance = _create_active_instance(
            paper_client, type_code="ai_market_agent_strategy", parameters=AI_VALID_PARAMS
        )
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)[0]["payload"]
        assert payload["signal"] == "HOLD"
        assert payload["confidence"] == 0
        assert payload["risk_flags"] == ["ai_unavailable"]

    def test_ai_provider_error_produces_conservative_hold(self, paper_client, redis_client, monkeypatch):
        from shared.ai_provider import AIProviderError

        fake = _FakeAIProvider(error=AIProviderError("quota dépassé"))
        monkeypatch.setattr(strategy_agent, "_build_ai_provider", lambda _redis: fake)

        instance = _create_active_instance(
            paper_client, type_code="ai_market_agent_strategy", parameters=AI_VALID_PARAMS
        )
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)

        payload = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)[0]["payload"]
        assert payload["signal"] == "HOLD"
        assert payload["risk_flags"] == ["ai_unavailable"]

    def test_invalid_ai_output_produces_conservative_hold(self, paper_client, redis_client, monkeypatch):
        # `recommendation` au lieu de `signal`, entre autres champs manquants
        # -> hors schéma, repli HOLD explicite côté moteur (pas un crash du
        # tick, et jamais un signal fabriqué à partir d'une sortie invalide).
        fake = _FakeAIProvider(result={"recommendation": "MAYBE"})
        monkeypatch.setattr(strategy_agent, "_build_ai_provider", lambda _redis: fake)

        instance = _create_active_instance(
            paper_client, type_code="ai_market_agent_strategy", parameters=AI_VALID_PARAMS
        )
        evidence = {"bars": {"AAPL": {"1Day": _bars(_CROSSING_CLOSES)}}}
        _publish_analysis(execution_context_id=instance["execution_context_id"], evidence=evidence)

        strategy_agent.tick(engine, redis_client)  # ne doit jamais lever

        payload = _drain(redis_client, Streams.STRATEGY_PROPOSAL_CREATED)[0]["payload"]
        assert payload["signal"] == "HOLD"
        assert "invalid_ai_output" in payload["risk_flags"]


class TestPureHelpers:
    """Logique pure (pas de DB/Redis) — mêmes conventions que
    `TestFreshnessCheck`/`TestNormalizeBars` dans `test_market_agent.py`."""

    def test_confidence_for_signal(self):
        assert strategy_agent._confidence_for_signal("BUY") == 10000
        assert strategy_agent._confidence_for_signal("SELL") == 10000
        assert strategy_agent._confidence_for_signal("HOLD") == 0
        assert strategy_agent._confidence_for_signal("garbage") == 0

    def test_build_proposal_valid_output(self):
        proposal = strategy_agent._build_proposal({"signal": "BUY", "reasoning": "x"})
        assert proposal.signal == "BUY"
        assert proposal.confidence == 10000
        assert proposal.risk_flags == []

    def test_build_proposal_falls_back_to_hold_on_invalid_signal(self):
        proposal = strategy_agent._build_proposal({"signal": "NOT_A_SIGNAL", "reasoning": "x"})
        assert proposal.signal == "HOLD"
        assert proposal.confidence == 0
        assert proposal.risk_flags == ["invalid_strategy_output"]

    def test_build_proposal_falls_back_to_hold_on_non_dict(self):
        proposal = strategy_agent._build_proposal(None)
        assert proposal.signal == "HOLD"
        assert proposal.risk_flags == ["invalid_strategy_output"]

    def test_build_proposal_defaults_missing_reasoning(self):
        proposal = strategy_agent._build_proposal({"signal": "HOLD"})
        assert proposal.reasoning  # jamais vide malgré min_length=1

    def test_build_proposal_honors_engine_provided_confidence_and_risk_flags(self):
        # §B12 — trou d'architecture corrigé (voir docstring de
        # `_build_proposal`) : un moteur qui fournit sa propre confiance
        # valide et ses propres risk_flags n'est plus écrasé par la
        # convention 10000/0 déterministe.
        proposal = strategy_agent._build_proposal(
            {"signal": "BUY", "confidence": 6321, "reasoning": "x", "risk_flags": ["requires_human_approval"]}
        )
        assert proposal.confidence == 6321
        assert proposal.risk_flags == ["requires_human_approval"]

    def test_build_proposal_ignores_out_of_range_confidence(self):
        # confidence hors [0, 10000] -> pas fait confiance, repli sur la
        # convention déterministe plutôt qu'une StrategyProposal invalide.
        proposal = strategy_agent._build_proposal({"signal": "BUY", "confidence": 99999, "reasoning": "x"})
        assert proposal.confidence == 10000

    def test_build_proposal_ignores_non_string_risk_flags(self):
        proposal = strategy_agent._build_proposal({"signal": "HOLD", "reasoning": "x", "risk_flags": ["ok", 42]})
        assert proposal.risk_flags == []

    def test_extract_bars_missing_symbol_or_timeframe_returns_empty(self):
        evidence = {"bars": {"AAPL": {"1Day": [{"close": 1.0}]}}}
        assert strategy_agent._extract_bars(evidence, "AAPL", "1Day") == [{"close": 1.0}]
        assert strategy_agent._extract_bars(evidence, "AAPL", "5Min") == []
        assert strategy_agent._extract_bars(evidence, "MSFT", "1Day") == []
        assert strategy_agent._extract_bars(evidence, "AAPL", None) == []
        assert strategy_agent._extract_bars({}, "AAPL", "1Day") == []

    def test_parse_bar_timestamp_tolerant(self):
        assert strategy_agent._parse_bar_timestamp("2024-01-01T00:00:00Z") is not None
        assert strategy_agent._parse_bar_timestamp(1700000000) is not None
        assert strategy_agent._parse_bar_timestamp("garbage") is None
        assert strategy_agent._parse_bar_timestamp(None) is None

    def test_manifest_capabilities_tolerant(self):
        assert strategy_agent._manifest_capabilities({"required_capabilities": ["ai"]}) == ["ai"]
        assert strategy_agent._manifest_capabilities({}) == []
        assert strategy_agent._manifest_capabilities(None) == []
        assert strategy_agent._manifest_capabilities("garbage") == []

    def test_load_engine_module_rejects_suspicious_type_code(self):
        assert strategy_agent._load_engine_module("../../etc/passwd") is None
        assert strategy_agent._load_engine_module("os; import os") is None
        assert strategy_agent._load_engine_module("does_not_exist") is None

    def test_load_engine_module_loads_the_real_strategy(self):
        module = strategy_agent._load_engine_module("moving_average_crossover")
        assert module is not None
        assert hasattr(module, "evaluate")

    def test_load_engine_module_loads_the_ai_strategy(self):
        # §B12 — prouve que le module de la nouvelle stratégie IA se charge
        # bien via le même loader dynamique que les deux stratégies
        # déterministes, aucun chemin d'import séparé.
        module = strategy_agent._load_engine_module("ai_market_agent_strategy")
        assert module is not None
        assert hasattr(module, "evaluate")

    def test_build_ai_provider_returns_none_without_api_key(self, redis_client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert strategy_agent._build_ai_provider(redis_client) is None

    def test_build_ai_provider_returns_provider_with_api_key(self, redis_client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        provider = strategy_agent._build_ai_provider(redis_client)
        assert provider is not None
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
