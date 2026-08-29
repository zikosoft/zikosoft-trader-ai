
from __future__ import annotations

import csv
from datetime import UTC, datetime

import pytest

from scripts import alpaca_cli_backtest as backtest


def _write_csv(tmp_path, rows: list[dict], fieldnames: list[str]):
    path = tmp_path / "bars.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


class TestLoadBarsCsv:
    def test_parses_alpaca_cli_style_columns(self, tmp_path):
        # Colonnes telles que documentées par l'Alpaca CLI officiel
        # (t/o/h/l/c/v) — non vérifiées en direct (aucun accès réseau réel
        # depuis cette sandbox), voir hypothèse 5 de la docstring du script.
        rows = [
            {"t": "2025-01-01T00:00:00Z", "o": "10", "h": "11", "l": "9", "c": "10.5", "v": "1000"},
            {"t": "2025-01-02T00:00:00Z", "o": "10.5", "h": "12", "l": "10", "c": "11.5", "v": "1200"},
        ]
        path = _write_csv(tmp_path, rows, ["t", "o", "h", "l", "c", "v"])
        bars = backtest.load_bars_csv(path)
        assert len(bars) == 2
        assert bars[0]["close"] == 10.5
        assert bars[0]["timestamp"] < bars[1]["timestamp"]

    def test_tolerates_alternate_column_names(self, tmp_path):
        rows = [{"timestamp": "2025-01-01T00:00:00Z", "close": "10.5"}]
        path = _write_csv(tmp_path, rows, ["timestamp", "close"])
        bars = backtest.load_bars_csv(path)
        assert bars[0]["close"] == 10.5

    def test_sorts_out_of_order_rows(self, tmp_path):
        rows = [
            {"t": "2025-01-02T00:00:00Z", "c": "11.5"},
            {"t": "2025-01-01T00:00:00Z", "c": "10.5"},
        ]
        path = _write_csv(tmp_path, rows, ["t", "c"])
        bars = backtest.load_bars_csv(path)
        assert [b["close"] for b in bars] == [10.5, 11.5]

    def test_raises_clear_error_on_empty_or_unrecognized_csv(self, tmp_path):
        rows = [{"foo": "bar"}]
        path = _write_csv(tmp_path, rows, ["foo"])
        with pytest.raises(ValueError, match="aucune bougie exploitable"):
            backtest.load_bars_csv(path)


class TestRunBacktest:
    """Série synthétique construite à la main : plate pendant 12 points puis
    un saut -> un seul croisement haussier univoque avec
    `moving_average_crossover` (mêmes hypothèses de construction que
    `tests/test_strategy_agent.py::_CROSSING_CLOSES`), pour vérifier le
    calcul de rendement par un calcul manuel simple plutôt qu'un résultat
    opaque."""

    def _bars(self, closes: list[float]) -> list[dict]:
        return [
            {"timestamp": datetime(2025, 1, i + 1, tzinfo=UTC), "close": c} for i, c in enumerate(closes)
        ]

    def test_buy_and_hold_to_end_matches_hand_computed_return(self):
        # Achat au croisement (bougie 13, cours 50.0), jamais de signal de
        # vente ensuite -> position encore ouverte, valorisée au dernier
        # cours (15e bougie, 50.0, série plate après l'achat).
        closes = [10.0] * 12 + [50.0] * 3
        bars = self._bars(closes)
        params = {"short_period": 2, "long_period": 4, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}
        report = backtest.run_backtest(
            bars=bars, type_code="moving_average_crossover", params=params, initial_capital=10_000.0
        )
        # Achat à 50.0, revente (mark-to-market) à 50.0 -> rendement stratégie 0%.
        assert report["strategy_return_pct"] == pytest.approx(0.0, abs=1e-9)
        # Benchmark : achat à 10.0 (premier cours), valorisé à 50.0 -> +400%.
        assert report["benchmark_return_pct"] == pytest.approx(400.0, abs=1e-9)
        assert report["still_open_at_end"] is True
        assert len(report["trades"]) == 0

    def test_buy_then_sell_produces_one_closed_trade(self):
        # Croisement haussier (bougie 13, 10->50) puis krach qui met 2
        # bougies à faire franchir la moyenne longue à la baisse (vérifié
        # par calcul : SMA2/SMA4 croisent à la bougie 15, pas la 14, la
        # moyenne longue restant tirée vers le haut par le pic à 50.0) ->
        # vente à la bougie 15. Calcul manuel : achat à 50.0, vente à 1.0
        # -> -98% sur ce trade.
        closes = [10.0] * 12 + [50.0, 1.0, 1.0, 1.0]
        bars = self._bars(closes)
        params = {"short_period": 2, "long_period": 4, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}
        report = backtest.run_backtest(
            bars=bars, type_code="moving_average_crossover", params=params, initial_capital=10_000.0
        )
        assert len(report["trades"]) == 1
        assert report["trades"][0]["pnl_pct"] == pytest.approx(-98.0, abs=1e-9)
        assert report["still_open_at_end"] is False
        assert report["strategy_return_pct"] == pytest.approx(-98.0, abs=1e-9)

    def test_no_signal_ever_produces_zero_return_and_no_trades(self):
        bars = self._bars([10.0] * 20)  # série plate, jamais de croisement
        params = {"short_period": 2, "long_period": 4, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}
        report = backtest.run_backtest(
            bars=bars, type_code="moving_average_crossover", params=params, initial_capital=10_000.0
        )
        assert report["trades"] == []
        assert report["strategy_return_pct"] == pytest.approx(0.0)
        assert report["still_open_at_end"] is False

    def test_rejects_unsupported_strategy(self):
        with pytest.raises(ValueError, match="non supportée"):
            backtest.run_backtest(
                bars=self._bars([10.0, 11.0]), type_code="ai_market_agent_strategy", params={}, initial_capital=1000.0
            )


class TestFormatReport:
    def test_report_mentions_lookahead_caveat(self):
        bars = TestRunBacktest()._bars([10.0] * 12 + [50.0] * 3)
        params = {"short_period": 2, "long_period": 4, "stop_loss_pct": 2.0, "take_profit_pct": 4.0}
        report = backtest.run_backtest(
            bars=bars, type_code="moving_average_crossover", params=params, initial_capital=10_000.0
        )
        output = backtest.format_report(report, symbol="TEST")
        assert "look-ahead" in output
        assert "TEST" in output


class TestDefaultParams:
    def test_default_params_come_from_beginner_profile(self):
        params = backtest._default_params("moving_average_crossover")
        assert params["short_period"] == 10
        assert params["long_period"] == 30
