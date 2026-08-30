"""B19 (Étape A) — shared/shared/replay_market_data.py. Aucune dépendance
infra (PostgreSQL/Redis) — logique pure + I/O fichier via `tmp_path`."""

from __future__ import annotations

import json

import pytest

from shared.replay_market_data import (
    ReplayBar,
    ReplayDatasetError,
    ReplayMarketDataProvider,
    build_dataset,
    load_dataset,
    save_dataset,
    validate_no_blocking_gaps,
)

TS = [f"2026-08-31T13:{m:02d}:00+00:00" for m in range(30, 35)]  # 5 minutes, 13:30-13:34 UTC


def _bars_by_symbol(symbols=("AAPL", "MSFT"), timestamps=TS, base_price=100.0):
    out = {}
    for i, symbol in enumerate(symbols):
        out[symbol] = {
            ts: {"open": base_price + i, "high": base_price + i + 1, "low": base_price + i - 1, "close": base_price + i + 0.5, "volume": 1000.0}
            for ts in timestamps
        }
    return out


class TestBuildDataset:
    def test_builds_shared_timestamp_axis(self):
        dataset = build_dataset(
            dataset_id="test-2026-08-31", trading_day="2026-08-31", timezone="America/New_York",
            bars_by_symbol=_bars_by_symbol(),
        )
        assert dataset.symbols == ("AAPL", "MSFT")
        assert dataset.timestamps == tuple(TS)
        assert len(dataset.bars["AAPL"]) == len(dataset.bars["MSFT"]) == 5

    def test_no_shared_timestamps_raises(self):
        bars = {"AAPL": {TS[0]: {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}}, "MSFT": {"2026-08-31T14:00:00+00:00": {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}}}
        with pytest.raises(ReplayDatasetError, match="aucun horodatage commun"):
            build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=bars)

    def test_more_than_10_percent_dropped_raises(self):
        """Un symbole qui perd >10% de ses horodatages par rapport à l'axe
        partagé signale un trou structurel, pas une poignée de minutes
        isolées — rejeté plutôt que silencieusement dégradé."""
        aapl_ts = [f"2026-08-31T13:{m:02d}:00+00:00" for m in range(0, 20)]  # 20 minutes
        shared_ts = aapl_ts[:15]  # MSFT n'a que 15/20 -> 25% manquant
        bars = {
            "AAPL": {ts: {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for ts in aapl_ts},
            "MSFT": {ts: {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1} for ts in shared_ts},
        }
        with pytest.raises(ReplayDatasetError, match="trou structurel probable"):
            build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=bars)

    def test_blocking_gap_on_shared_axis_raises(self):
        timestamps = [TS[0], TS[1], "2026-08-31T14:30:00+00:00"]  # gros trou après les 2 premières
        bars = _bars_by_symbol(timestamps=timestamps)
        with pytest.raises(ReplayDatasetError, match="trou\\(s\\) bloquant"):
            build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=bars)

    def test_empty_input_raises(self):
        with pytest.raises(ReplayDatasetError, match="aucun symbole"):
            build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol={})

    def test_checksum_is_deterministic_and_content_sensitive(self):
        d1 = build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=_bars_by_symbol())
        d2 = build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=_bars_by_symbol())
        assert d1.checksum == d2.checksum

        altered = _bars_by_symbol()
        altered["AAPL"][TS[0]]["close"] = 999.0
        d3 = build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=altered)
        assert d3.checksum != d1.checksum


class TestValidateNoBlockingGaps:
    def test_no_gaps(self):
        assert validate_no_blocking_gaps(symbol="AAPL", timestamps=TS, expected_interval_seconds=60) == []

    def test_gap_reported(self):
        timestamps = [TS[0], "2026-08-31T13:45:00+00:00"]
        issues = validate_no_blocking_gaps(symbol="AAPL", timestamps=timestamps, expected_interval_seconds=60)
        assert len(issues) == 1
        assert "AAPL" in issues[0]


class TestSaveLoadDataset:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "dataset.json"
        original = build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=_bars_by_symbol())
        save_dataset(original, path)
        reloaded = load_dataset(path)
        assert reloaded == original

    def test_missing_file_raises_with_helpful_message(self, tmp_path):
        with pytest.raises(ReplayDatasetError, match="fetch_replay_dataset.py"):
            load_dataset(tmp_path / "does_not_exist.json")

    def test_tampered_checksum_raises(self, tmp_path):
        path = tmp_path / "dataset.json"
        dataset = build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=_bars_by_symbol())
        save_dataset(dataset, path)
        raw = json.loads(path.read_text())
        raw["bars"]["AAPL"][0]["close"] = 12345.0  # modifié sans recalculer le checksum
        path.write_text(json.dumps(raw))
        with pytest.raises(ReplayDatasetError, match="checksum"):
            load_dataset(path)


class TestReplayMarketDataProvider:
    def _provider(self) -> ReplayMarketDataProvider:
        dataset = build_dataset(dataset_id="x", trading_day="2026-08-31", timezone="UTC", bars_by_symbol=_bars_by_symbol())
        return ReplayMarketDataProvider(dataset)

    def test_starts_before_first_bar(self):
        provider = self._provider()
        assert provider.index == -1
        assert provider.current_bars() == {}
        assert provider.current_timestamp() is None
        assert provider.is_finished is False

    def test_advance_moves_one_bar_at_a_time(self):
        provider = self._provider()
        bars = provider.advance()
        assert provider.index == 0
        assert set(bars) == {"AAPL", "MSFT"}
        assert isinstance(bars["AAPL"], ReplayBar)
        assert provider.current_timestamp() == TS[0]

    def test_advance_past_the_end_returns_none_never_raises(self):
        provider = self._provider()
        for _ in range(5):
            assert provider.advance() is not None
        assert provider.is_finished is True
        assert provider.advance() is None  # ne lève jamais
        assert provider.is_finished is True

    def test_reset_is_deterministic_restart(self):
        """§checklist "Deux replays identiques reçoivent les mêmes données"
        / "Restart déterministe"."""
        provider = self._provider()
        first_run = [provider.advance() for _ in range(5)]
        provider.reset()
        assert provider.index == -1
        second_run = [provider.advance() for _ in range(5)]
        assert first_run == second_run

    def test_seek_restores_a_known_position(self):
        provider = self._provider()
        provider.advance()
        provider.advance()
        provider.advance()
        saved_index = provider.index

        fresh_provider = self._provider()  # simule une reconstruction sans état (une requête HTTP, voir routers/replay.py)
        fresh_provider.seek(saved_index)
        assert fresh_provider.index == saved_index
        assert fresh_provider.current_bars() == provider.current_bars()

    def test_seek_out_of_bounds_raises(self):
        provider = self._provider()
        with pytest.raises(ValueError, match="hors bornes"):
            provider.seek(999)
        with pytest.raises(ValueError, match="hors bornes"):
            provider.seek(-2)

    def test_seek_minus_one_is_valid_reset_equivalent(self):
        provider = self._provider()
        provider.advance()
        provider.seek(-1)
        assert provider.index == -1
        assert provider.current_bars() == {}

    def test_summary_reflects_current_state(self):
        provider = self._provider()
        provider.advance()
        provider.advance()
        summary = provider.summary()
        assert summary["current_index"] == 1
        assert summary["total_bars"] == 5
        assert summary["is_finished"] is False
        assert summary["dataset_id"] == "x"
