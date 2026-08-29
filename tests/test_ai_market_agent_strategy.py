"""B12 — AI Market Agent Strategy : tests unitaires du moteur (§B12
"Confiance minimale", "Validation humaine configurable", "Protections
obligatoires", "Tests du structured output"). Tests directs du module
`strategies.ai_market_agent_strategy.*`, sans passer par le Strategy Agent
(déjà couvert bout-en-bout par
`tests/test_strategy_agent.py::TestAiMarketAgentStrategyEndToEnd`) — même
niveau que `tests/test_moving_average_crossover.py`/`test_rsi_reversal.py`.

Aucune dépendance au SDK `anthropic` : `evaluate()` n'appelle jamais le SDK
directement, seulement l'interface abstraite `AIProvider` (voir docstring
de `engine.py`) — un simple double duck-typé suffit, tourne sous le venv
backend standard comme les deux autres stratégies."""

from __future__ import annotations

from shared.ai_provider import AIProviderError
from strategies.ai_market_agent_strategy.definition import DEFINITION
from strategies.ai_market_agent_strategy.engine import evaluate, validate_parameters


class _FakeAIProvider:
    def __init__(self, *, result: dict | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict] = []

    def structured_complete(self, *, prompt, schema, tier, context_label=""):
        self.calls.append({"prompt": prompt, "schema": schema, "tier": tier, "context_label": context_label})
        if self._error is not None:
            raise self._error
        return self._result


def _bars(closes: list[float]) -> list[dict]:
    return [{"close": c} for c in closes]


PARAMS = {
    "timeframe": "1Day",
    "analysis_frequency": "1Day",
    "risk_posture": "balanced",
    "min_confidence": 5000,
    "max_notional_usd": 1000.0,
    "require_human_approval": True,
}


class TestValidateParameters:
    def test_valid_parameters_produce_no_errors(self):
        assert validate_parameters(PARAMS) == []

    def test_min_confidence_out_of_range_rejected(self):
        errors = validate_parameters({**PARAMS, "min_confidence": 20000})
        assert any("min_confidence" in e for e in errors)

    def test_non_positive_max_notional_rejected(self):
        errors = validate_parameters({**PARAMS, "max_notional_usd": 0})
        assert any("max_notional_usd" in e for e in errors)


class TestEvaluate:
    def test_no_provider_returns_conservative_hold(self):
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=None, symbol="AAPL")
        assert result["signal"] == "HOLD"
        assert result["confidence"] == 0
        assert result["risk_flags"] == ["ai_unavailable"]

    def test_provider_error_returns_conservative_hold(self):
        fake = _FakeAIProvider(error=AIProviderError("timeout"))
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="AAPL")
        assert result["signal"] == "HOLD"
        assert result["risk_flags"] == ["ai_unavailable"]

    def test_valid_ai_output_passes_through_with_its_own_confidence(self):
        fake = _FakeAIProvider(
            result={"signal": "BUY", "confidence": 9000, "reasoning": "tendance nette", "risk_flags": ["x"]}
        )
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="AAPL")
        assert result["signal"] == "BUY"
        assert result["confidence"] == 9000
        assert "x" in result["risk_flags"]
        # §B12 "requires_human_approval" ajouté en plus des flags IA (pas à
        # la place) puisque PARAMS.require_human_approval=True.
        assert "requires_human_approval" in result["risk_flags"]

    def test_hold_signal_never_gets_human_approval_flag(self):
        fake = _FakeAIProvider(result={"signal": "HOLD", "confidence": 9000, "reasoning": "rien à faire"})
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="AAPL")
        assert result["signal"] == "HOLD"
        assert "requires_human_approval" not in result["risk_flags"]

    def test_low_confidence_signal_is_downgraded_to_hold(self):
        # PARAMS.min_confidence = 5000
        fake = _FakeAIProvider(result={"signal": "SELL", "confidence": 1000, "reasoning": "signal faible"})
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="AAPL")
        assert result["signal"] == "HOLD"
        assert "below_min_confidence" in result["risk_flags"]
        assert "requires_human_approval" not in result["risk_flags"]
        assert "SELL" in result["reasoning"]  # signal original tracé, pas juste effacé

    def test_no_human_approval_flag_when_not_required(self):
        params = {**PARAMS, "require_human_approval": False}
        fake = _FakeAIProvider(result={"signal": "BUY", "confidence": 9000, "reasoning": "x"})
        result = evaluate(_bars([10, 11, 12]), params, ai_provider=fake, symbol="AAPL")
        assert "requires_human_approval" not in result["risk_flags"]

    def test_invalid_signal_enum_returns_conservative_hold(self):
        fake = _FakeAIProvider(result={"signal": "MAYBE", "confidence": 9000, "reasoning": "x"})
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="AAPL")
        assert result["signal"] == "HOLD"
        assert result["risk_flags"] == ["invalid_ai_output"]

    def test_missing_required_field_returns_conservative_hold(self):
        fake = _FakeAIProvider(result={"signal": "BUY", "confidence": 9000})  # reasoning manquant
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="AAPL")
        assert result["signal"] == "HOLD"
        assert result["risk_flags"] == ["invalid_ai_output"]

    def test_non_dict_output_returns_conservative_hold(self):
        fake = _FakeAIProvider(result="not a dict")
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="AAPL")
        assert result["signal"] == "HOLD"
        assert result["risk_flags"] == ["invalid_ai_output"]

    def test_confidence_out_of_bounds_returns_conservative_hold(self):
        fake = _FakeAIProvider(result={"signal": "BUY", "confidence": 20000, "reasoning": "x"})
        result = evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="AAPL")
        assert result["signal"] == "HOLD"
        assert result["risk_flags"] == ["invalid_ai_output"]

    def test_prompt_includes_symbol_and_risk_posture(self):
        fake = _FakeAIProvider(result={"signal": "HOLD", "confidence": 0, "reasoning": "x"})
        evaluate(_bars([10, 11, 12]), PARAMS, ai_provider=fake, symbol="MSFT")
        assert "MSFT" in fake.calls[0]["prompt"]
        assert "balanced" in fake.calls[0]["prompt"]

    def test_evaluate_requires_ai_provider_keyword(self):
        # Signature volontairement différente des deux moteurs déterministes
        # (voir docstring de engine.py) — appeler sans `ai_provider=` doit
        # lever, pas silencieusement se comporter comme les autres moteurs.
        import pytest

        with pytest.raises(TypeError):
            evaluate(_bars([10, 11, 12]), PARAMS)


class TestDefinitionMatchesEngineContract:
    def test_all_parameters_used_by_engine_are_declared_in_schema(self):
        declared = set(DEFINITION.parameter_schema["properties"].keys())
        used_by_engine = {"timeframe", "risk_posture", "min_confidence", "max_notional_usd", "require_human_approval"}
        assert used_by_engine <= declared

    def test_required_capabilities_declares_ai(self):
        # §B12 — seule stratégie du registre à déclarer une capacité,
        # contrairement à moving_average_crossover/rsi_reversal.
        assert DEFINITION.required_capabilities == ["ai"]
