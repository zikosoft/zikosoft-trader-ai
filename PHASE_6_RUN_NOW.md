# Phase 6 — Run a five-minute Paper demo now

This release fixes the gap where the Strategy form accepted `5Min` while the
Market Agent only fetched `1Day` bars. It also makes `analysis_frequency` a
real scheduling control, exposes safe strategy editing, and preserves a
manually expanded Agent Room on any page.

## Start the updated release

1. Keep your existing `.env` file private. It is intentionally not included in
   the delivery archive and must not be replaced by `.env.example`.
2. Build and start the project from the extracted folder:

   ```bash
   docker compose up -d --build
   ```

3. Wait until **System Health** shows Market Agent, Strategy Agent, Risk
   Critic Agent and Execution Explanation Agent as healthy.

## Test now with a five-minute cadence

In **Settings**, use the following temporary demo controls if you need more
than the remaining daily quota. The deployment hard cap still remains the
owner-controlled value from `.env`.

| Setting | Demo value |
| --- | --- |
| High-stakes model | `claude-haiku-4-5` |
| Low-stakes model | `claude-haiku-4-5` |
| Calls per minute | `3` |
| Calls per day | `100` |
| Temperature | `0.1` |
| Max output tokens | `256` |
| Daily budget | `$5` (or at most the displayed hard cap) |

In **Strategies**:

1. Pause or stop `AAPL Claude Options Demo`.
2. Click the new pencil icon to edit it.
3. Set `timeframe` to `5Min` and `analysis_frequency` to `5Min`.
4. Keep `AAPL` as the only symbol.
5. Set `require_human_approval` to `true`.
6. Save, then activate the strategy.

The first eligible fresh five-minute candle triggers an evaluation immediately;
there is no need to wait for the next five-minute boundary after activation.
After that, all three built-in strategies are eligible again at most once every
five minutes when their `timeframe` is set to `5Min` (the AI strategy may use
its explicit `analysis_frequency` instead).

## Expected live debate

The Agent Room is event-based, not a permanently chatting bot. For each
eligible evaluation, the expected sequence is:

1. Strategy Agent publishes the Claude proposal.
2. Risk Critic Agent publishes its review.
3. Risk Engine publishes the deterministic option/risk outcome.
4. Execution Explanation Agent publishes a user-facing explanation.

`Ask Ziko` only uses Claude after a user explicitly asks a question. The
invisible Market Agent summary is disabled by default in this release, so it
does not spend Claude calls every five seconds without creating a visible
discussion. Set `MARKET_AGENT_AI_SUMMARY_ENABLED=true` in `.env` only if that
separate background summary is intentionally needed.

## Agent Room layout

On any application page, select the docked or fullscreen icon in the Agent
Room header. The chosen expanded mode remains active while staying on that
page. Navigating away from the dedicated **AI Agent Room** page still reduces
the route-opened fullscreen view to compact mode, preventing it from covering
the destination page.
