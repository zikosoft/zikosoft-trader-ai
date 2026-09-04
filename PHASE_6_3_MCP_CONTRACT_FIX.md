# Phase 6.3 — Alpaca MCP market-data contract fix

## Confirmed cause

The live Docker logs confirmed that the application was successfully starting
both Market Agent and Strategy Agent, but Market Agent sent an invalid MCP
payload for every stock-data request:

```text
get_stock_bars: missing required argument `symbols`
get_stock_bars: unexpected keyword argument `symbol`
get_stock_snapshot: query parameter `symbols` is required
```

Alpaca's MCP stock tools require the plural `symbols` parameter even for one
ticker. The previous singular `symbol` payload caused HTTP 400 responses,
leaving no real bar timestamp. Market Agent correctly marked that evidence
stale, and Strategy Agent correctly refused to evaluate it. This is why
`last_evaluated_at` stayed `null` and Live Debate was empty.

## Fix

- `get_stock_snapshot` now receives `{ "symbols": "DELL" }`.
- `get_stock_bars` now receives `{ "symbols": "DELL", "timeframe": "5Min", "limit": 100 }`.
- Multi-symbol snapshot response envelopes are safely unwrapped for quote and
  freshness processing.
- The existing active-strategy-symbol and newest-bar freshness fixes remain in
  place.

## Apply and verify

Keep the existing `.env`, extract this archive, then rebuild the agent image:

```bash
docker compose up -d --build
```

Wait 15 seconds, open **Strategies**, and refresh once. For an active DELL
strategy, `last_evaluated_at` must become a timestamp. **AI Agent Room → Live
Debate** must then show at least the real Strategy Agent message.

If it does not, collect the new logs after this rebuild:

```bash
docker compose logs --tail=120 market-agent strategy-agent
```

Do not send `.env` or any API key.
