# Phase 6.2 — Live Debate immediate Paper test

## What this release fixes

Two defects blocked the real Paper decision pipeline before it could create a
Live Debate entry:

1. Market Agent gathered evidence only for the old `AAPL`, `MSFT`, and `SPY`
   demo list. An active `DELL` strategy therefore received no bars or options
   chain.
2. Freshness was calculated from the oldest candle in the 100-candle history.
   A valid five-minute series was consequently marked stale before Strategy
   Agent was allowed to evaluate it.

Active strategy symbols now determine the read-only MCP market calls (up to
ten unique symbols), and freshness uses the newest observed market timestamp.
No Alpaca live endpoint is added or used.

## Install

1. Extract this archive over the project directory.
2. Keep your existing `.env` file unchanged.
3. Rebuild and restart the stack. Agent code is baked into its Docker image,
   so a frontend-only restart is not sufficient:

```bash
docker compose up -d --build
```

4. Wait until the Market Agent, Strategy Agent, and Portfolio Worker are
   healthy in **System Health**.

## Immediate DELL test strategy

Stop or delete the previous test strategy first, then create and activate
exactly one strategy with these values. They deliberately make the RSI test
directional; they are a functional Paper demo, not a production investment
configuration.

| Field | Value |
| --- | --- |
| Strategy type | `RSI Reversal` |
| Name | `DELL RSI Forced 5m Paper Demo` |
| Symbol | `DELL` |
| Profile | `Expert` |
| Timeframe | `5Min` |
| RSI period | `2` |
| Oversold threshold | `0` |
| Overbought threshold | `0.01` |
| Stop loss | `1` % |
| Take profit | `2` % |

## Expected result

The first evaluation is due immediately when a fresh MCP market response
arrives; it does not wait for a five-minute boundary. In roughly 10–20 seconds
after the services are healthy, **AI Agent Room → Live Debate** must contain a
real **Strategy Agent** message for `DELL`.

The message can say either:

- `BUY` → candidate long Call; or
- `SELL` → candidate long Put; or
- a visible `HOLD` with `options_unavailable` if Alpaca MCP did not return a
  usable, quoted DELL option contract.

The last case still proves that the real Market → Strategy pipeline works and
is safe: the application never falls back to trading DELL stock. A Paper order
requires a directional signal, usable option contract and quote, fresh
portfolio buying power, and a Risk Engine approval.

## If Live Debate is still empty

Run the following command from the project root and send the output of the
last 200 lines (do not include `.env` contents):

```bash
docker compose logs --tail=200 market-agent strategy-agent
```

The browser `favicon` 404 and the React DOM warnings are unrelated to agent
evaluation. The replay `GET /api/portfolio/summary 404` is also a separate
frontend replay-mode bug; it does not block Paper Live Debate and will be
handled after this Paper pipeline proof.
