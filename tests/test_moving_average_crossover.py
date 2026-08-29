"""B12 — Moving Average Crossover : tests unitaires du calcul déterministe
(§B12 "Calcul déterministe", "Validation short period < long period",
"Stop-loss et take-profit", "Tests unitaires"). Import direct des modules
de stratégie (`strategies.moving_average_crossover.*`) — pas via le loader
dynamique de B11 (déjà couvert séparément par
`tests/test_strategy_registry.py`, qui prouve que ce même module se charge
bien comme plugin)."""

from __future__ import annotations

from strategies._base.indicators import simple_moving_average
from strategies.moving_average_crossover.definition import DEFINITION
from strategies.moving_average_crossover.engine import evaluate, validate_parameters


def _bars(closes: list[float]) -> list[dict]:
    return [{"close": c} for c in closes]


class TestSimpleMovingAverage:
    def test_first_period_minus_one_points_are_none(self):
        result = simple_moving_average([1, 2, 3, 4, 5], period=3)
        assert result[:2] == [None, None]

    def test_hand_computed_values(self):
        # SMA(3) sur [1,2,3,4,5] : [None, None, 2.0, 3.0, 4.0]
        result = simple_moving_average([1, 2, 3, 4, 5], period=3)
        assert result == [None, None, 2.0, 3.0, 4.0]

    def test_period_one_returns_the_series_unchanged(self):
        assert simple_moving_average([1.0, 2.0, 3.0], period=1) == [1.0, 2.0, 3.0]

    def test_rejects_non_positive_period(self):
        import pytest

        with pytest.raises(ValueError):
            simple_moving_average([1, 2, 3], period=0)


class TestValidateParameters:
    def test_valid_parameters_produce_no_errors(self):
        errors = validate_parameters(
            {"short_period": 10, "long_period": 30, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}
        )
        assert errors == []

    def test_short_period_not_less_than_long_period_rejected(self):
        errors = validate_parameters(
            {"short_period": 30, "long_period": 30, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}
        )
        assert any("short_period" in e for e in errors)

    def test_non_positive_stop_loss_rejected(self):
        errors = validate_parameters(
            {"short_period": 10, "long_period": 30, "stop_loss_pct": 0, "take_profit_pct": 4.0}
        )
        assert any("stop_loss_pct" in e for e in errors)

    def test_non_positive_take_profit_rejected(self):
        errors = validate_parameters(
            {"short_period": 10, "long_period": 30, "stop_loss_pct": 2.0, "take_profit_pct": -1}
        )
        assert any("take_profit_pct" in e for e in errors)


class TestEvaluate:
    PARAMS = {"short_period": 2, "long_period": 4, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}

    def test_not_enough_bars_returns_hold(self):
        result = evaluate(_bars([1, 2, 3]), self.PARAMS)
        assert result["signal"] == "HOLD"
        assert "pas assez de bougies" in result["reasoning"]

    def test_bullish_crossover_produces_buy(self):
        # Construit une série où SMA(2) était <= SMA(4) puis passe strictement
        # au-dessus sur la dernière bougie.
        # closes:            10,  10,  10,  10,  20
        # SMA(2):  [None, 10, 10, 10, 15]
        # SMA(4):  [None, None, None, 10, 12.5]
        # Avant-dernier point (idx 3): SMA2=10 <= SMA4=10 (égal, couvert par <=)
        # Dernier point (idx 4): SMA2=15 > SMA4=12.5 -> croisement haussier
        closes = [10, 10, 10, 10, 20]
        result = evaluate(_bars(closes), self.PARAMS)
        assert result["signal"] == "BUY"
        assert result["short_ma"] == 15.0
        assert result["long_ma"] == 12.5

    def test_bearish_crossover_produces_sell(self):
        # Symétrique du cas haussier : la courte descend sous la longue.
        closes = [10, 10, 10, 10, 0]
        result = evaluate(_bars(closes), self.PARAMS)
        assert result["signal"] == "SELL"
        assert result["short_ma"] == 5.0
        assert result["long_ma"] == 7.5

    def test_no_crossover_produces_hold(self):
        # Série plate : les deux moyennes restent égales, jamais de
        # croisement strict.
        closes = [10, 10, 10, 10, 10, 10]
        result = evaluate(_bars(closes), self.PARAMS)
        assert result["signal"] == "HOLD"
        assert "pas de croisement" in result["reasoning"]

    def test_evaluate_is_deterministic_same_input_same_output(self):
        closes = [10, 11, 9, 12, 8, 13, 20]
        first = evaluate(_bars(closes), self.PARAMS)
        second = evaluate(_bars(closes), self.PARAMS)
        assert first == second


class TestDefinitionMatchesEngineContract:
    """§B11 "défenses en profondeur" — la définition (validée par le
    Strategy Registry, JSON Schema inclus) et le moteur de calcul doivent
    rester cohérents : tout paramètre requis par `evaluate`/`validate_parameters`
    doit être déclaré dans `parameter_schema`."""

    def test_all_parameters_used_by_engine_are_declared_in_schema(self):
        declared = set(DEFINITION.parameter_schema["properties"].keys())
        used_by_engine = {"short_period", "long_period", "stop_loss_pct", "take_profit_pct"}
        assert used_by_engine <= declared

    def test_required_capabilities_is_empty_deterministic_strategy(self):
        # §B12 "Calcul déterministe" — aucun appel IA, donc aucune capacité
        # requise (contrairement à la future "AI Market Agent Strategy").
        assert DEFINITION.required_capabilities == []
