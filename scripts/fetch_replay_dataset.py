#!/usr/bin/env python3
"""B19 (Étape A) — génère le dataset fixe du Replay Engine
(`replay_data/dataset.json`) à partir d'exports CSV de l'Alpaca CLI officiel.

**Ce que ce script fait :** lit un CSV de bougies intraday PAR SYMBOLE
(export `alpaca data bars ...`, format déjà utilisé par
`scripts/alpaca_cli_backtest.py`, B12/D021), construit l'axe de temps
partagé entre tous les symboles fournis (`shared.replay_market_data.build_dataset`
— rejette les trous structurels et bloquants plutôt que de les masquer),
calcule un fingerprint/checksum, et écrit un `ReplayDataset` versionné à
`replay_data/dataset.json` (§checklist B19 "Sauvegarder OHLCV versionné",
"Ajouter fingerprint/checksum", "Valider absence de trous bloquants").

**Ce que ce script n'invente jamais :** il ne contient AUCUNE donnée de
marché — même limite honnête que `scripts/alpaca_cli_backtest.py` (B12) et
tout le reste du projet vis-à-vis d'Alpaca : cette sandbox de développement
n'a ni accès réseau sortant vers Alpaca ni tes identifiants. C'est donc TOI
(Zac), pas Claude, qui dois exécuter les exports CSV puis ce script, avec
tes propres clés.

## Comment produire le dataset réel (à faire par TOI, pas par Claude)

```bash
# 1. Choisir UNE journée de bourse fixe et 3 à 5 symboles liquides (§checklist
#    "Choisir journée fixe" / "Choisir 3 à 5 symboles") — ex. AAPL, MSFT, SPY
#    (mêmes symboles que agents/market_agent/main.py::DEMO_WATCHLIST, pour la
#    continuité avec le reste de la démo).

# 2. Exporter les bougies 1 minute de CETTE journée, un CSV par symbole
#    (l'export Alpaca CLI est mono-symbole, voir alpaca_cli_backtest.py) :
alpaca data bars --symbol AAPL --start 2026-08-31 --end 2026-09-01 \\
    --timeframe 1Min --csv > aapl_2026-08-31.csv
alpaca data bars --symbol MSFT --start 2026-08-31 --end 2026-09-01 \\
    --timeframe 1Min --csv > msft_2026-08-31.csv
alpaca data bars --symbol SPY  --start 2026-08-31 --end 2026-09-01 \\
    --timeframe 1Min --csv > spy_2026-08-31.csv

# 3. Construire le dataset versionné (depuis la racine du monorepo) :
python scripts/fetch_replay_dataset.py \\
    --trading-day 2026-08-31 \\
    --bars AAPL=aapl_2026-08-31.csv \\
    --bars MSFT=msft_2026-08-31.csv \\
    --bars SPY=spy_2026-08-31.csv

# 4. Vérifier le résumé affiché (nombre de bougies, checksum, éventuels
#    trous rejetés) puis committer `replay_data/dataset.json` — c'est le
#    fichier que `ReplayMarketDataProvider` (Étape A) et le futur pipeline
#    Replay complet (Étape B) liront.
```

Usage (aide complète) : `python scripts/fetch_replay_dataset.py --help`

## Limite honnête assumée

Le format exact des colonnes du CSV Alpaca CLI n'a pas pu être vérifié en
direct depuis cette sandbox (même limite que `alpaca_cli_backtest.py`) — le
parseur ci-dessous est donc volontairement tolérant aux noms de colonnes
usuels, même principe que `_pick`/`load_bars_csv` de ce même script B12."""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.replay_market_data import (  # noqa: E402
    DEFAULT_REPLAY_DATASET_PATH,
    ReplayDatasetError,
    build_dataset,
    save_dataset,
)

_TIMESTAMP_KEYS = ("t", "timestamp", "time")
_OPEN_KEYS = ("o", "open")
_HIGH_KEYS = ("h", "high")
_LOW_KEYS = ("l", "low")
_CLOSE_KEYS = ("c", "close")
_VOLUME_KEYS = ("v", "volume")


def _pick(row: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _parse_timestamp_utc(raw: str) -> str:
    """Renvoie un horodatage ISO8601 UTC normalisé — clé d'alignement entre
    symboles dans `build_dataset` (voir sa docstring : l'axe partagé est une
    intersection EXACTE de chaînes, donc toute divergence de format entre
    deux exports CSV casserait silencieusement l'alignement sans cette
    normalisation)."""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"horodatage illisible dans le CSV : {raw!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def load_symbol_csv(path: Path) -> dict[str, dict]:
    """Retourne `{iso_timestamp_utc: {"open","high","low","close","volume"}}`
    pour UN symbole — voir docstring du module pour le format CSV attendu."""
    bars: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_ts = _pick(row, _TIMESTAMP_KEYS)
            raw_close = _pick(row, _CLOSE_KEYS)
            if raw_ts is None or raw_close is None:
                continue
            ts = _parse_timestamp_utc(raw_ts)
            bars[ts] = {
                "open": float(_pick(row, _OPEN_KEYS) or raw_close),
                "high": float(_pick(row, _HIGH_KEYS) or raw_close),
                "low": float(_pick(row, _LOW_KEYS) or raw_close),
                "close": float(raw_close),
                "volume": float(_pick(row, _VOLUME_KEYS) or 0.0),
            }
    if not bars:
        raise ValueError(
            f"aucune bougie exploitable dans {path} — colonnes attendues parmi "
            f"{_TIMESTAMP_KEYS} (horodatage) et {_CLOSE_KEYS} (clôture)"
        )
    return bars


def _parse_bars_arg(raw: str) -> tuple[str, Path]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"--bars attend SYMBOL=chemin.csv, reçu : {raw!r}")
    symbol, _, path = raw.partition("=")
    return symbol.strip().upper(), Path(path.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trading-day", required=True, help="Journée de bourse fixe, format YYYY-MM-DD")
    parser.add_argument(
        "--bars", required=True, action="append", type=_parse_bars_arg, metavar="SYMBOL=chemin.csv",
        help="Répétable, un par symbole (3 à 5 attendus, §checklist)",
    )
    parser.add_argument("--timezone", default="America/New_York", help="Fuseau horaire documenté de la source (§checklist)")
    parser.add_argument("--dataset-id", default=None, help="Défaut : 'replay-<trading-day>'")
    parser.add_argument("--interval-seconds", type=int, default=60, help="Intervalle attendu entre bougies (60 = 1Min)")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPLAY_DATASET_PATH)
    args = parser.parse_args(argv)

    if len(args.bars) < 3:
        print(f"Avertissement : seulement {len(args.bars)} symbole(s) fourni(s) (§checklist recommande 3 à 5).", file=sys.stderr)

    dataset_id = args.dataset_id or f"replay-{args.trading_day}"

    bars_by_symbol: dict[str, dict] = {}
    for symbol, path in args.bars:
        try:
            bars_by_symbol[symbol] = load_symbol_csv(path)
        except (ValueError, OSError) as exc:
            print(f"Erreur en lisant {symbol} ({path}) : {exc}", file=sys.stderr)
            return 1
        print(f"{symbol} : {len(bars_by_symbol[symbol])} bougies lues depuis {path}")

    try:
        dataset = build_dataset(
            dataset_id=dataset_id,
            trading_day=args.trading_day,
            timezone=args.timezone,
            bars_by_symbol=bars_by_symbol,
            expected_interval_seconds=args.interval_seconds,
        )
    except ReplayDatasetError as exc:
        print(f"Dataset rejeté : {exc}", file=sys.stderr)
        return 1

    save_dataset(dataset, args.output)

    print()
    print("=== Dataset Replay construit ===")
    print(f"dataset_id       : {dataset.dataset_id}")
    print(f"Journée          : {dataset.trading_day} ({dataset.timezone})")
    print(f"Symboles         : {', '.join(dataset.symbols)}")
    print(f"Bougies (axe partagé) : {len(dataset.timestamps)} ({dataset.timestamps[0]} -> {dataset.timestamps[-1]})")
    print(f"Checksum (sha256) : {dataset.checksum}")
    print(f"Écrit vers        : {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
