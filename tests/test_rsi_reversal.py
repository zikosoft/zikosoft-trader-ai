"""B12 — RSI Reversal : tests unitaires du calcul déterministe (§B12 "Calcul
RSI", "Validation seuil achat < seuil vente", "Stop-loss et take-profit",
"Tests unitaires"). Même structure que `tests/test_moving_average_crossover.py`
— import direct des modules de stratégie, pas via le loader dynamique de
B11 (déjà couvert séparément par `tests/test_strategy_registry.py`)."""

from __future__ import annotations

import pytest

from strategies._base.indicators import relative_strength_index
from strategies.rsi_reversal.definition import DEFINITION
from strategies.rsi_reversal.engine import evaluate, validate_parameters


def _bars(closes: list[float]) -> list[dict]:
    return [{"close": c} for c in closes]


class TestRelativeStrengthIndex:
    def test_first_period_points_are_none(self):
        # Contrairement à `simple_moving_average` (padding à period-1), un
        # RSI a besoin de `period` VARIATIONS -> `period` premiers points
        # `None`, le point d'indice `period` est le premier exploitable.
        result = relative_strength_index([10, 11, 12, 11], period=3)
        assert result[:3] == [None, None, None]

    def test_hand_computed_values(self):
        # closes = [10, 11, 12, 11, 10, 12, 14], period=3
        # variations : +1,+1,-1,-1,+2,+2 -> gains=[0,1,1,0,0,2,2] losses=[0,0,0,1,1,0,0]
        # idx3 : avg_gain=(1+1+0)/3=0.6667, avg_loss=(0+0+1)/3=0.3333 -> RSI=100-100/(1+2)=66.67
        # idx4 : avg_gain=(1+0+0)/3=0.3333, avg_loss=(0+1+1)/3=0.6667 -> RSI=100-100/(1+0.5)=33.33
        # idx5 : avg_gain=(0+0+2)/3=0.6667, avg_loss=(1+1+0)/3=0.6667 -> RSI=100-100/2=50.0
        # idx6 : avg_gain=(0+2+2)/3=1.3333, avg_loss=(1+0+0)/3=0.3333 -> RSI=100-100/5=80.0
        result = relative_strength_index([10, 11, 12, 11, 10, 12, 14], period=3)
        assert result[3] == pytest.approx(66.6667, abs=1e-3)
        assert result[4] == pytest.approx(33.3333, abs=1e-3)
        assert result[5] == pytest.approx(50.0)
        assert result[6] == pytest.approx(80.0)

    def test_no_losses_at_all_returns_100(self):
        result = relative_strength_index([10, 11, 12, 13], period=3)
        assert result[3] == 100.0

    def test_flat_series_returns_neutral_50(self):
        result = relative_strength_index([10, 10, 10, 10], period=3)
        assert result[3] == 50.0

    def test_rejects_non_positive_period(self):
        with pytest.raises(ValueError):
            relative_strength_index([1, 2, 3], period=0)


class TestValidateParameters:
    def test_valid_parameters_produce_no_errors(self):
        errors = validate_parameters(
            {"oversold_threshold": 30, "overbought_threshold": 70, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}
        )
        assert errors == []

    def test_oversold_not_less_than_overbought_rejected(self):
        errors = validate_parameters(
            {"oversold_threshold": 70, "overbought_threshold": 70, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}
        )
        assert any("oversold_threshold" in e for e in errors)

    def test_non_positive_stop_loss_rejected(self):
        errors = validate_parameters(
            {"oversold_threshold": 30, "overbought_threshold": 70, "stop_loss_pct": 0, "take_profit_pct": 4.0}
        )
        assert any("stop_loss_pct" in e for e in errors)

    def test_non_positive_take_profit_rejected(self):
        errors = validate_parameters(
            {"oversold_threshold": 30, "overbought_threshold": 70, "stop_loss_pct": 2.0, "take_profit_pct": -1}
        )
        assert any("take_profit_pct" in e for e in errors)


class TestEvaluate:
    PARAMS = {"rsi_period": 3, "oversold_threshold": 30, "overbought_threshold": 70, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}

    def test_not_enough_bars_returns_hold(self):
        result = evaluate(_bars([10, 11, 12]), self.PARAMS)
        assert result["signal"] == "HOLD"
        assert "pas assez de bougies" in result["reasoning"]
        assert result["rsi"] is None

    def test_overbought_produces_sell(self):
        # RSI(3) = 80.0 sur cette série (voir TestRelativeStrengthIndex.test_hand_computed_values) >= 70
        closes = [10, 11, 12, 11, 10, 12, 14]
        result = evaluate(_bars(closes), self.PARAMS)
        assert result["signal"] == "SELL"
        assert result["rsi"] == pytest.approx(80.0)

    def test_oversold_produces_buy(self):
        # Symétrique du cas de vente : série descendante -> RSI(3) = 20.0 <= 30
        closes = [14, 12, 10, 11, 12, 10, 8]
        result = evaluate(_bars(closes), self.PARAMS)
        assert result["signal"] == "BUY"
        assert result["rsi"] == pytest.approx(20.0)

    def test_between_thresholds_produces_hold(self):
        closes = [10, 10.5, 10, 10.5, 10, 10.5, 10]
        result = evaluate(_bars(closes), self.PARAMS)
        assert result["signal"] == "HOLD"
        assert "pas de signal" in result["reasoning"]

    def test_evaluate_is_deterministic_same_input_same_output(self):
        closes = [10, 11, 9, 12, 8, 13, 20]
        first = evaluate(_bars(closes), self.PARAMS)
        second = evaluate(_bars(closes), self.PARAMS)
        assert first == second


class TestDefinitionMatchesEngineContract:
    def test_all_parameters_used_by_engine_are_declared_in_schema(self):
        declared = set(DEFINITION.parameter_schema["properties"].keys())
        used_by_engine = {"rsi_period", "oversold_threshold", "overbought_threshold", "stop_loss_pct", "take_profit_pct"}
        assert used_by_engine <= declared

    def test_required_capabilities_is_empty_deterministic_strategy(self):
        assert DEFINITION.required_capabilities == []
