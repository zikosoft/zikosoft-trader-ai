# `replay_data/`

Contains the fixed Replay Engine dataset (`dataset.json`). The repository
currently ships a full-session **synthetic UI fixture** for a non-empty,
credentials-free Replay screen. It is not an Alpaca export, is not historical
market evidence, and must never be shown as an executed-trade demonstration.

The Replay screen can display a deterministic options-path preview from this
fixture. That preview uses the existing Moving Average Crossover logic, but
its option contract/quote is explicitly synthetic: it does not call Alpaca,
MCP, Claude, the Risk Engine, or the Order Worker. Paper Trading remains the
only environment that proves agents, real option data, risk approval, and an
actual order.

To replace this fixture with a real historical dataset, generate it from your
own Alpaca data and keep the same destination:

```
python scripts/fetch_replay_dataset.py \
    --trading-day 2026-08-31 \
    --bars AAPL=aapl.csv --bars MSFT=msft.csv --bars SPY=spy.csv \
    --output replay_data/dataset.json
```

(voir le docstring de `scripts/fetch_replay_dataset.py` pour comment
produire les CSV d'entrée avec la CLI Alpaca).
