"""Deterministic, read-only options preview for the Replay UI.

Replay is a credentials-free visual fixture.  This module deliberately runs
one of the existing deterministic strategies (Moving Average Crossover) on
the immutable replay candles, then illustrates how a directional signal maps
to one long option.  Its contract and quote are *synthetic*, are never
published to agents or workers, and cannot be used as order evidence.

The Paper path remains the only path that may use Alpaca option-chain data,
risk gates and the Order Worker.  Keeping this preview pure also prevents a
Replay click from writing an order, spending an AI token, or calling Alpaca.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil, floor
from typing import Literal

from strategies.moving_average_crossover.engine import evaluate as evaluate_moving_average

from .options import OptionContractCandidate, OptionInstrument, OptionQuote, OptionSelectionPolicy, select_option_contract
from .replay_market_data import ReplayDataset

ReplayPreviewSignal = Literal["BUY", "SELL", "HOLD"]
ReplayPreviewAction = Literal["LONG_CALL", "LONG_PUT", "NO_ORDER"]

SOURCE = "SYNTHETIC_REPLAY_FIXTURE"
RISK_STATUS = "NOT_EVALUATED_IN_REPLAY"
EXECUTION_STATUS = "NOT_SENT_REPLAY"
STRATEGY_TYPE_CODE = "moving_average_crossover"
# The advanced defaults are suitable for the included one-minute fixture and
# are intentionally fixed here so reset + advance is reproducible.
STRATEGY_PARAMETERS = {"short_period": 9, "long_period": 21}


@dataclass(frozen=True)
class ReplayOptionsPreview:
    """A presentational result only; never an executable proposal."""

    source: str
    strategy_type_code: str
    strategy_parameters: dict[str, int]
    current_index: int
    underlying_symbol: str | None
    signal: ReplayPreviewSignal
    signal_reasoning_code: str
    option_action: ReplayPreviewAction
    option_instrument: OptionInstrument | None
    risk_status: str
    execution_status: str
    is_order_evidence: bool = False


def _underlying_symbol(dataset: ReplayDataset) -> str:
    """Prefer AAPL for the included fixture, then fall back deterministically."""
    return "AAPL" if "AAPL" in dataset.symbols else dataset.symbols[0]


def _expiry_for(trading_day: date) -> date:
    """Select the Friday nearest to 18 DTE while staying within 7--30 DTE."""
    candidates = [trading_day + timedelta(days=offset) for offset in range(7, 31)]
    fridays = [candidate for candidate in candidates if candidate.weekday() == 4]
    return min(fridays, key=lambda candidate: abs((candidate - trading_day).days - 18))


def _strike_for(underlying_price: float, signal: ReplayPreviewSignal) -> float:
    # A deliberately simple synthetic ATM/slightly-OTM rule. It is not a
    # market-data model and is only used to visualize the long call/put map.
    increment = 5.0 if underlying_price < 500 else 10.0
    if signal == "BUY":
        return round(ceil(underlying_price / increment) * increment, 2)
    return round(floor(underlying_price / increment) * increment, 2)


def _occ_symbol(*, underlying_symbol: str, expiration_date: date, option_type: str, strike_price: float) -> str:
    right = "C" if option_type == "call" else "P"
    strike_millis = int(round(strike_price * 1000))
    return f"{underlying_symbol.upper()[:6]}{expiration_date:%y%m%d}{right}{strike_millis:08d}"


def _synthetic_option(
    *,
    signal: ReplayPreviewSignal,
    underlying_symbol: str,
    underlying_price: float,
    trading_day: date,
) -> OptionInstrument:
    """Build a clearly synthetic contract through the shared selector.

    Reusing ``select_option_contract`` verifies the same BUY->call / SELL->put
    mapping and long-option constraints used by Paper.  The candidate and
    quote below are fixture values, never Alpaca values.
    """
    option_type = "call" if signal == "BUY" else "put"
    expiration_date = _expiry_for(trading_day)
    strike_price = _strike_for(underlying_price, signal)
    symbol = _occ_symbol(
        underlying_symbol=underlying_symbol,
        expiration_date=expiration_date,
        option_type=option_type,
        strike_price=strike_price,
    )

    # Fixture-only illustrative pricing: enough to exercise premium, spread
    # and whole-contract selection without pretending to be a market quote.
    intrinsic_distance = abs(underlying_price - strike_price)
    mid_price = round(max(1.5, 2.25 + intrinsic_distance * 0.15), 2)
    bid_price = round(mid_price * 0.985, 2)
    ask_price = round(mid_price * 1.015, 2)
    if ask_price <= bid_price:
        ask_price = round(bid_price + 0.05, 2)

    selected = select_option_contract(
        signal=signal,
        underlying_price=underlying_price,
        as_of=trading_day,
        policy=OptionSelectionPolicy(max_premium=500.0, max_contracts=1),
        contracts=[
            OptionContractCandidate(
                symbol=symbol,
                underlying_symbol=underlying_symbol,
                option_type=option_type,
                expiration_date=expiration_date,
                strike_price=strike_price,
                tradable=True,
                status="active",
                contract_size=100,
                open_interest=1000,
            )
        ],
        quotes=[
            OptionQuote(
                symbol=symbol,
                bid_price=bid_price,
                ask_price=ask_price,
                bid_size=10,
                ask_size=10,
                delta=0.5 if signal == "BUY" else -0.5,
            )
        ],
    )
    if selected is None:  # defensive: this function is called only for BUY/SELL
        raise RuntimeError("synthetic Replay option selection unexpectedly returned no contract")
    return selected


def build_replay_options_preview(dataset: ReplayDataset, *, current_index: int) -> ReplayOptionsPreview:
    """Build the same visual preview for the same immutable candle index.

    No database, Redis, MCP, provider, risk engine or order worker is touched
    here. A pre-first-candle session intentionally remains HOLD with no
    illustrative contract.
    """
    if current_index < 0:
        return ReplayOptionsPreview(
            source=SOURCE,
            strategy_type_code=STRATEGY_TYPE_CODE,
            strategy_parameters=dict(STRATEGY_PARAMETERS),
            current_index=current_index,
            underlying_symbol=None,
            signal="HOLD",
            signal_reasoning_code="INSUFFICIENT_BARS",
            option_action="NO_ORDER",
            option_instrument=None,
            risk_status=RISK_STATUS,
            execution_status=EXECUTION_STATUS,
        )

    if current_index >= len(dataset.timestamps):
        raise ValueError(f"current_index {current_index} is outside the Replay dataset")

    underlying_symbol = _underlying_symbol(dataset)
    bars = [bar.to_dict() for bar in dataset.bars[underlying_symbol][: current_index + 1]]
    raw = evaluate_moving_average(bars, dict(STRATEGY_PARAMETERS))
    signal = raw["signal"]
    if signal not in ("BUY", "SELL", "HOLD"):
        signal = "HOLD"

    if signal == "HOLD":
        return ReplayOptionsPreview(
            source=SOURCE,
            strategy_type_code=STRATEGY_TYPE_CODE,
            strategy_parameters=dict(STRATEGY_PARAMETERS),
            current_index=current_index,
            underlying_symbol=underlying_symbol,
            signal="HOLD",
            signal_reasoning_code=(
                "INSUFFICIENT_BARS"
                if raw.get("short_ma") is None or raw.get("long_ma") is None
                else "NO_CROSSOVER"
            ),
            option_action="NO_ORDER",
            option_instrument=None,
            risk_status=RISK_STATUS,
            execution_status=EXECUTION_STATUS,
        )

    underlying_price = float(bars[-1]["close"])
    instrument = _synthetic_option(
        signal=signal,
        underlying_symbol=underlying_symbol,
        underlying_price=underlying_price,
        trading_day=date.fromisoformat(dataset.trading_day),
    )
    return ReplayOptionsPreview(
        source=SOURCE,
        strategy_type_code=STRATEGY_TYPE_CODE,
        strategy_parameters=dict(STRATEGY_PARAMETERS),
        current_index=current_index,
        underlying_symbol=underlying_symbol,
        signal=signal,
        signal_reasoning_code="CROSSOVER_UP" if signal == "BUY" else "CROSSOVER_DOWN",
        option_action="LONG_CALL" if signal == "BUY" else "LONG_PUT",
        option_instrument=instrument,
        risk_status=RISK_STATUS,
        execution_status=EXECUTION_STATUS,
    )
