"""B19 (Étape A) — scripts/fetch_replay_dataset.py. Même discipline que
test_alpaca_cli_backtest.py (B12) : logique pure + fichiers `tmp_path`,
aucune dépendance infra."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_replay_dataset import load_symbol_csv, main  # noqa: E402
from shared.replay_market_data import load_dataset  # noqa: E402

TIMESTAMPS = [f"2026-08-19T13:{m:02d}:00Z" for m in range(30, 33)]  # 3 minutes


def _write_csv(path: Path, *, timestamps=TIMESTAMPS, base_price=100.0, columns=("t", "o", "h", "l", "c", "v")) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for ts in timestamps:
            writer.writerow([ts, base_price, base_price + 1, base_price - 1, base_price + 0.5, 1000])


class TestLoadSymbolCsv:
    def test_parses_alpaca_cli_style_columns(self, tmp_path):
        path = tmp_path / "aapl.csv"
        _write_csv(path)
        bars = load_symbol_csv(path)
        assert len(bars) == 3
        first_key = sorted(bars)[0]
        assert bars[first_key]["close"] == 100.5

    def test_tolerates_alternate_column_names(self, tmp_path):
        path = tmp_path / "aapl.csv"
        _write_csv(path, columns=("timestamp", "open", "high", "low", "close", "volume"))
        bars = load_symbol_csv(path)
        assert len(bars) == 3

    def test_normalizes_timestamps_to_utc_iso(self, tmp_path):
        path = tmp_path / "aapl.csv"
        _write_csv(path, timestamps=["2026-08-19T13:30:00Z"])
        bars = load_symbol_csv(path)
        assert list(bars.keys()) == ["2026-08-19T13:30:00+00:00"]

    def test_empty_csv_raises(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("t,c\n")
        with pytest.raises(ValueError, match="aucune bougie exploitable"):
            load_symbol_csv(path)


class TestMain:
    def test_builds_and_saves_dataset(self, tmp_path):
        aapl_csv = tmp_path / "aapl.csv"
        msft_csv = tmp_path / "msft.csv"
        spy_csv = tmp_path / "spy.csv"
        for path in (aapl_csv, msft_csv, spy_csv):
            _write_csv(path)
        output = tmp_path / "dataset.json"

        exit_code = main(
            [
                "--trading-day", "2026-08-19",
                "--bars", f"AAPL={aapl_csv}",
                "--bars", f"MSFT={msft_csv}",
                "--bars", f"SPY={spy_csv}",
                "--output", str(output),
            ]
        )

        assert exit_code == 0
        assert output.exists()
        dataset = load_dataset(output)  # revalide le checksum au passage
        assert dataset.symbols == ("AAPL", "MSFT", "SPY")
        assert len(dataset.timestamps) == 3
        assert dataset.dataset_id == "replay-2026-08-19"

    def test_fewer_than_3_symbols_warns_but_still_succeeds(self, tmp_path, capsys):
        aapl_csv = tmp_path / "aapl.csv"
        _write_csv(aapl_csv)
        output = tmp_path / "dataset.json"

        exit_code = main(
            ["--trading-day", "2026-08-19", "--bars", f"AAPL={aapl_csv}", "--output", str(output)]
        )
        assert exit_code == 0
        assert "Avertissement" in capsys.readouterr().err

    def test_rejected_dataset_returns_nonzero_and_writes_nothing(self, tmp_path):
        aapl_csv = tmp_path / "aapl.csv"
        msft_csv = tmp_path / "msft.csv"
        _write_csv(aapl_csv, timestamps=["2026-08-19T13:30:00Z"])
        _write_csv(msft_csv, timestamps=["2026-08-19T15:30:00Z"])  # aucun horodatage commun
        output = tmp_path / "dataset.json"

        exit_code = main(
            ["--trading-day", "2026-08-19", "--bars", f"AAPL={aapl_csv}", "--bars", f"MSFT={msft_csv}", "--output", str(output)]
        )
        assert exit_code == 1
        assert not output.exists()

    def test_missing_input_file_returns_nonzero(self, tmp_path):
        output = tmp_path / "dataset.json"
        exit_code = main(["--trading-day", "2026-08-19", "--bars", f"AAPL={tmp_path / 'missing.csv'}", "--output", str(output)])
        assert exit_code == 1
