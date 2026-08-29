#!/usr/bin/env python3
"""B12 — artefact de backtest via l'Alpaca CLI (§D021, AVANCEMENT.md).

**Ce que fait ce script :** rejoue une stratégie déterministe déjà livrée
(`moving_average_crossover` ou `rsi_reversal`, voir `strategies/`) sur un
historique de bougies exporté par l'Alpaca CLI officiel
(https://github.com/alpacahq/cli), et compare son rendement à un benchmark
"buy-and-hold" sur la même période — objectif D021 : rendre visible la
**troisième** technologie nommée par l'organisateur (Trading API, MCP
server, CLI), au-delà des deux premières déjà exercées par B10 (session MCP)
et B07 (Trading API via `alpaca_client.py`).

**Ce que ce script n'invente jamais :** il ne contient AUCUNE donnée de
marché — il lit un fichier CSV que TOI (pas Claude) dois générer avec
l'Alpaca CLI et tes propres clés Alpaca (jamais partagées avec Claude, voir
CONTRIBUTING.md). Cette sandbox de développement n'a ni accès réseau sortant
vers l'API Alpaca ni tes identifiants — impossible d'y produire un artefact
réel ; ce script est donc livré prêt à l'emploi, à exécuter par toi, plutôt
que le résultat d'une exécution fabriquée ici.

**Réutilisation volontaire du moteur de production, pas un second moteur de
backtest dupliqué** : ce script appelle directement
`strategies.<type_code>.engine.evaluate()` — EXACTEMENT le même code que le
Strategy Agent (B13) exécute en production — de sorte qu'un backtest reflète
fidèlement le comportement réel de la stratégie, pas une réimplémentation
séparée qui pourrait diverger silencieusement.

## Hypothèses formalisées (§D021 "formaliser les hypothèses")

1. Aucun frais de transaction ni slippage simulé (Alpaca Paper n'en applique
   pas non plus).
2. Position pleine (100% du capital) ou totalement à plat — pas de sizing
   partiel, pas de position courte (long-only en V1).
3. **Biais de "look-ahead" assumé et documenté, pas caché** : l'exécution
   simulée a lieu au COURS DE CLÔTURE de la MÊME bougie qui a généré le
   signal. En production réelle, le signal n'est disponible qu'après la
   clôture de cette bougie (voir `agents/strategy_agent/main.py`) — un ordre
   réel serait donc passé sur l'ouverture ou la clôture suivante, à un prix
   légèrement différent. Cette simplification gonfle légèrement le rendement
   simulé par rapport à une exécution réelle ; elle n'est pas corrigée ici
   pour rester simple, mais elle doit être mentionnée dans toute conclusion
   tirée de cet artefact.
4. Benchmark = achat de la position maximale au premier cours de clôture
   disponible, conservée sans aucune vente jusqu'au dernier cours de
   clôture de la période — mêmes données, même période exacte que la
   stratégie testée.
5. Format CSV de l'Alpaca CLI non vérifié en direct (aucun accès réseau
   réel à Alpaca depuis cette sandbox, même limite documentée pour B10/B13)
   — le parseur ci-dessous est volontairement tolérant aux noms de colonnes
   usuels (`t`/`timestamp`/`time`, `c`/`close`), même principe que
   `agents/market_agent/main.py::_normalize_bars`.

## Comment produire l'artefact réel (à faire par TOI, pas par Claude)

```bash
# 1. Installer l'Alpaca CLI officiel (une fois) :
brew install alpacahq/tap/cli
# ou : go install github.com/alpacahq/cli/cmd/alpaca@latest

# 2. T'authentifier avec TES clés Alpaca Paper (jamais saisies ici) :
alpaca profile login

# 3. Exporter un historique de bougies au format CSV :
alpaca data bars --symbol AAPL --start 2025-01-01 --end 2025-12-31 \\
    --timeframe 1Day --csv > aapl_2025.csv

# 4. Lancer ce script sur l'export (depuis la racine du monorepo) :
python scripts/alpaca_cli_backtest.py --input aapl_2025.csv \\
    --strategy moving_average_crossover --symbol AAPL

# 5. Copier la sortie (ou une capture d'écran du terminal) dans le README,
#    section "Artefact CLI Alpaca" — voir le README pour l'emplacement exact.
```

Usage (aide complète) : `python scripts/alpaca_cli_backtest.py --help`
"""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUPPORTED_STRATEGIES = ("moving_average_crossover", "rsi_reversal")
# §B12 — la troisième stratégie (`ai_market_agent_strategy`) est
# volontairement EXCLUE de cet outil : chaque bougie évaluée déclencherait
# un vrai appel `AIProvider.structured_complete()` (coût réel en tokens,
# D026), ce qui rendrait un backtest sur des centaines de bougies coûteux
# et lent sans bénéfice pour la démonstration du CLI Alpaca — hors scope
# de cet artefact, documenté ici plutôt que silencieusement absent.

_TIMESTAMP_KEYS = ("t", "timestamp", "time")
_CLOSE_KEYS = ("c", "close")


def _pick(row: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _parse_timestamp(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"horodatage illisible dans le CSV : {raw!r}") from exc


def load_bars_csv(path: Path) -> list[dict]:
    """Parseur tolérant (voir hypothèse 5 ci-dessus) — lève une erreur claire
    plutôt qu'un backtest silencieusement faux si le CSV ne contient ni
    horodatage ni clôture exploitables."""
    bars: list[dict] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_ts = _pick(row, _TIMESTAMP_KEYS)
            raw_close = _pick(row, _CLOSE_KEYS)
            if raw_ts is None or raw_close is None:
                continue
            bars.append({"timestamp": _parse_timestamp(raw_ts), "close": float(raw_close)})
    if not bars:
        raise ValueError(
            f"aucune bougie exploitable dans {path} — colonnes attendues parmi "
            f"{_TIMESTAMP_KEYS} (horodatage) et {_CLOSE_KEYS} (clôture)"
        )
    bars.sort(key=lambda b: b["timestamp"])
    return bars


def _load_engine(type_code: str):
    if type_code not in SUPPORTED_STRATEGIES:
        raise ValueError(f"stratégie non supportée par ce backtest : {type_code!r} (voir {SUPPORTED_STRATEGIES})")
    return importlib.import_module(f"strategies.{type_code}.engine")


def _default_params(type_code: str) -> dict:
    definition_module = importlib.import_module(f"strategies.{type_code}.definition")
    return dict(definition_module.DEFINITION.defaults_by_profile["beginner"])


def run_backtest(*, bars: list[dict], type_code: str, params: dict, initial_capital: float) -> dict:
    """Rejoue `strategies.<type_code>.engine.evaluate()` bougie par bougie —
    voir hypothèses formalisées dans la docstring du module, notamment le
    biais de look-ahead assumé (hypothèse 3)."""
    engine_module = _load_engine(type_code)

    position = "FLAT"  # ou "LONG"
    shares = 0.0
    cash = initial_capital
    trades: list[dict] = []
    entry_price: float | None = None
    entry_timestamp: datetime | None = None

    # `evaluate()` a besoin d'un historique — on lui donne tout l'historique
    # disponible JUSQU'À la bougie courante à chaque itération (fenêtre
    # croissante), exactement comme le Strategy Agent le fait en production
    # via `evidence["bars"]` (B10/B13) : jamais de données futures visibles.
    for i in range(1, len(bars) + 1):
        window = bars[:i]
        current = window[-1]
        result = engine_module.evaluate(window, params)
        signal = result.get("signal")

        if signal == "BUY" and position == "FLAT":
            shares = cash / current["close"]
            cash = 0.0
            position = "LONG"
            entry_price = current["close"]
            entry_timestamp = current["timestamp"]
        elif signal == "SELL" and position == "LONG":
            proceeds = shares * current["close"]
            trades.append(
                {
                    "entry_timestamp": entry_timestamp,
                    "entry_price": entry_price,
                    "exit_timestamp": current["timestamp"],
                    "exit_price": current["close"],
                    "pnl_pct": (current["close"] - entry_price) / entry_price * 100 if entry_price else 0.0,
                }
            )
            cash = proceeds
            shares = 0.0
            position = "FLAT"
            entry_price = None
            entry_timestamp = None

    last_close = bars[-1]["close"]
    final_equity = cash + shares * last_close
    strategy_return_pct = (final_equity - initial_capital) / initial_capital * 100

    first_close = bars[0]["close"]
    benchmark_shares = initial_capital / first_close
    benchmark_equity = benchmark_shares * last_close
    benchmark_return_pct = (benchmark_equity - initial_capital) / initial_capital * 100

    return {
        "type_code": type_code,
        "params": params,
        "period_start": bars[0]["timestamp"],
        "period_end": bars[-1]["timestamp"],
        "bar_count": len(bars),
        "trades": trades,
        "still_open_at_end": position == "LONG",
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "strategy_return_pct": strategy_return_pct,
        "benchmark_return_pct": benchmark_return_pct,
        "outperformance_pct": strategy_return_pct - benchmark_return_pct,
    }


def format_report(report: dict, *, symbol: str) -> str:
    lines = [
        "=== Artefact de backtest — Alpaca CLI (§D021) ===",
        f"Symbole            : {symbol}",
        f"Stratégie          : {report['type_code']}",
        f"Paramètres         : {json.dumps(report['params'], sort_keys=True)}",
        f"Période            : {report['period_start'].date()} -> {report['period_end'].date()} ({report['bar_count']} bougies)",
        f"Capital initial    : {report['initial_capital']:,.2f} $",
        f"Nombre de trades   : {len(report['trades'])}"
        + (" (position encore ouverte en fin de période, valorisée au dernier cours)" if report["still_open_at_end"] else ""),
        "",
    ]
    for idx, trade in enumerate(report["trades"], start=1):
        lines.append(
            f"  Trade {idx}: {trade['entry_timestamp'].date()} @ {trade['entry_price']:.2f} -> "
            f"{trade['exit_timestamp'].date()} @ {trade['exit_price']:.2f}  ({trade['pnl_pct']:+.2f}%)"
        )
    if report["trades"]:
        lines.append("")

    lines += [
        f"Rendement stratégie : {report['strategy_return_pct']:+.2f}%",
        f"Rendement benchmark (buy-and-hold) : {report['benchmark_return_pct']:+.2f}%",
        f"Surperformance vs. benchmark       : {report['outperformance_pct']:+.2f}%",
        "",
        "Rappel (voir docstring du module) : exécution simulée au cours de clôture de la",
        "bougie ayant généré le signal (biais de look-ahead assumé), aucun frais/slippage,",
        "long-only, position pleine ou totalement à plat.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path, help="CSV exporté par `alpaca data bars ... --csv`")
    parser.add_argument("--strategy", required=True, choices=SUPPORTED_STRATEGIES)
    parser.add_argument("--symbol", required=True, help="Uniquement pour l'affichage du rapport (le CSV est mono-symbole)")
    parser.add_argument(
        "--params",
        type=str,
        default=None,
        help="JSON de paramètres (défaut : profil 'beginner' de la stratégie, voir strategies/<type_code>/definition.py)",
    )
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    args = parser.parse_args(argv)

    bars = load_bars_csv(args.input)
    params = json.loads(args.params) if args.params else _default_params(args.strategy)

    errors = _load_engine(args.strategy).validate_parameters(params)
    if errors:
        print("Paramètres invalides :", *errors, sep="\n  - ", file=sys.stderr)
        return 1

    report = run_backtest(bars=bars, type_code=args.strategy, params=params, initial_capital=args.initial_capital)
    print(format_report(report, symbol=args.symbol))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
