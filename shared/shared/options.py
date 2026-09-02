"""Shared option-contract models and deterministic contract selection.

The selector is intentionally independent of Alpaca/network code. Agents can
feed it contracts from the Trading API and quotes from the option-chain
endpoint, while tests and Replay can provide the same normalized dictionaries
without credentials. A directional strategy signal is not an order until this
module returns a validated :class:`OptionInstrument`.
"""

from __future__ import annotations

from datetime import date
from math import floor
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

OptionType = Literal["call", "put"]


class OptionContractCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(min_length=1, max_length=50)
    underlying_symbol: str = Field(min_length=1, max_length=10)
    option_type: OptionType
    expiration_date: date
    strike_price: float = Field(gt=0)
    tradable: bool = True
    status: str = "active"
    contract_size: int = Field(default=100, gt=0)
    open_interest: int | None = Field(default=None, ge=0)


class OptionQuote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(min_length=1, max_length=50)
    bid_price: float = Field(gt=0)
    ask_price: float = Field(gt=0)
    bid_size: int | None = Field(default=None, ge=0)
    ask_size: int | None = Field(default=None, ge=0)
    delta: float | None = None


class OptionSelectionPolicy(BaseModel):
    """Conservative defaults for the hackathon Paper demonstration."""

    min_dte: int = Field(default=7, ge=1, le=365)
    max_dte: int = Field(default=30, ge=1, le=730)
    max_premium: float = Field(default=500.0, gt=0)
    max_spread_pct: float = Field(default=0.20, gt=0, le=1)
    max_contracts: int = Field(default=1, ge=1, le=100)
    target_delta: float = Field(default=0.50, gt=0, lt=1)


class OptionInstrument(BaseModel):
    """Fully specified long option instrument ready for an order command."""

    model_config = ConfigDict(frozen=True)

    asset_class: Literal["option"] = "option"
    underlying_symbol: str = Field(min_length=1, max_length=10)
    symbol: str = Field(min_length=1, max_length=50)
    option_type: OptionType
    expiration_date: date
    strike_price: float = Field(gt=0)
    bid_price: float = Field(gt=0)
    ask_price: float = Field(gt=0)
    limit_price: float = Field(gt=0)
    contract_size: int = Field(default=100, gt=0)
    quantity: int = Field(gt=0)
    estimated_premium: float = Field(gt=0)
    max_loss: float = Field(gt=0)
    spread_pct: float = Field(ge=0)
    open_interest: int | None = Field(default=None, ge=0)
    delta: float | None = None


class OptionSelectionError(ValueError):
    """Raised when no contract satisfies the deterministic policy."""


def normalize_option_contracts(raw: Any, *, underlying_symbol: str) -> list[dict[str, Any]]:
    """Normalize MCP/REST contract envelopes to selector dictionaries."""
    if isinstance(raw, Mapping):
        raw = raw.get("option_contracts") or raw.get("contracts") or raw.get("assets") or []
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        symbol = item.get("symbol")
        option_type = item.get("type") or item.get("option_type")
        expiration = item.get("expiration_date") or item.get("expirationDate")
        strike = item.get("strike_price") or item.get("strikePrice")
        if not symbol or not option_type or not expiration or strike is None:
            continue
        normalized.append(
            {
                "symbol": str(symbol),
                "underlying_symbol": str(item.get("underlying_symbol") or item.get("root_symbol") or underlying_symbol).upper(),
                "option_type": str(option_type).lower(),
                "expiration_date": str(expiration),
                "strike_price": strike,
                "tradable": bool(item.get("tradable", True)),
                "status": str(item.get("status") or "active").lower(),
                "contract_size": item.get("size") or item.get("contract_size") or 100,
                "open_interest": item.get("open_interest") or item.get("openInterest"),
            }
        )
    return normalized


def normalize_option_quotes(raw: Any) -> dict[str, dict[str, Any]]:
    """Normalize symbol-keyed option snapshots into selector quote fields."""
    if isinstance(raw, Mapping) and isinstance(raw.get("snapshots"), Mapping):
        raw = raw["snapshots"]
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for symbol, item in raw.items():
        if not isinstance(item, Mapping):
            continue
        quote = item.get("latestQuote") or item.get("latest_quote") or item.get("quote") or item
        greeks = item.get("greeks") or {}
        if not isinstance(quote, Mapping):
            continue
        bid = quote.get("bp") or quote.get("bid_price") or quote.get("bidPrice")
        ask = quote.get("ap") or quote.get("ask_price") or quote.get("askPrice")
        if bid is None or ask is None:
            continue
        result[str(symbol)] = {
            "symbol": str(symbol),
            "bid_price": bid,
            "ask_price": ask,
            "bid_size": quote.get("bs") or quote.get("bid_size"),
            "ask_size": quote.get("as") or quote.get("ask_size"),
            "delta": greeks.get("delta") if isinstance(greeks, Mapping) else item.get("delta"),
        }
    return result


def _candidate(value: OptionContractCandidate | Mapping[str, object]) -> OptionContractCandidate:
    return value if isinstance(value, OptionContractCandidate) else OptionContractCandidate.model_validate(value)


def _quote(value: OptionQuote | Mapping[str, object]) -> OptionQuote:
    return value if isinstance(value, OptionQuote) else OptionQuote.model_validate(value)


def select_option_contract(
    *,
    signal: Literal["BUY", "SELL", "HOLD"],
    underlying_price: float,
    contracts: Iterable[OptionContractCandidate | Mapping[str, object]],
    quotes: Mapping[str, OptionQuote | Mapping[str, object]] | Iterable[OptionQuote | Mapping[str, object]],
    as_of: date | None = None,
    policy: OptionSelectionPolicy | None = None,
) -> OptionInstrument | None:
    """Select one liquid long call/put for a directional signal.

    ``BUY`` maps to a call and ``SELL`` to a put. ``HOLD`` intentionally
    returns ``None``. The function never creates short options, spreads or a
    market order. The selected limit is the current ask, so the estimated
    premium/max loss is conservative for a long option.
    """
    if signal == "HOLD":
        return None
    if underlying_price <= 0:
        raise OptionSelectionError("underlying_price must be positive")
    policy = policy or OptionSelectionPolicy()
    if policy.min_dte > policy.max_dte:
        raise OptionSelectionError("min_dte must not exceed max_dte")
    today = as_of or date.today()
    desired_type: OptionType = "call" if signal == "BUY" else "put"

    if isinstance(quotes, Mapping):
        quote_by_symbol = {}
        for symbol, value in quotes.items():
            # Callers may naturally provide ``{symbol: {bid_price, ...}}``;
            # inject the key as the normalized quote symbol in that form.
            if isinstance(value, Mapping) and "symbol" not in value:
                value = {**value, "symbol": symbol}
            quote_by_symbol[symbol] = _quote(value)
    else:
        quote_by_symbol = {}
        for raw_quote in quotes:
            parsed = _quote(raw_quote)
            quote_by_symbol[parsed.symbol] = parsed

    eligible: list[tuple[tuple[float, float, float, float, float], OptionContractCandidate, OptionQuote, int, float, float]] = []
    for raw_contract in contracts:
        contract = _candidate(raw_contract)
        if contract.option_type != desired_type or not contract.tradable or contract.status != "active":
            continue
        dte = (contract.expiration_date - today).days
        if dte < policy.min_dte or dte > policy.max_dte:
            continue
        quote = quote_by_symbol.get(contract.symbol)
        if quote is None or quote.ask_price < quote.bid_price:
            continue
        mid = (quote.bid_price + quote.ask_price) / 2
        spread_pct = (quote.ask_price - quote.bid_price) / mid if mid > 0 else 1.0
        if spread_pct > policy.max_spread_pct:
            continue
        max_quantity = floor(policy.max_premium / (quote.ask_price * contract.contract_size))
        quantity = min(policy.max_contracts, max_quantity)
        if quantity < 1:
            continue
        estimated_premium = round(quote.ask_price * contract.contract_size * quantity, 2)
        strike_distance = abs(contract.strike_price / underlying_price - 1.0)
        delta_distance = abs(abs(quote.delta) - policy.target_delta) if quote.delta is not None else 0.25
        dte_distance = abs(dte - (policy.min_dte + policy.max_dte) / 2)
        open_interest_penalty = -(contract.open_interest or 0)
        score = (strike_distance, delta_distance, dte_distance, spread_pct, open_interest_penalty)
        eligible.append((score, contract, quote, quantity, estimated_premium, spread_pct))

    if not eligible:
        raise OptionSelectionError("no option contract satisfies the selection policy")
    _, contract, quote, quantity, estimated_premium, spread_pct = min(eligible, key=lambda item: item[0])
    limit_price = round(quote.ask_price, 2)
    return OptionInstrument(
        underlying_symbol=contract.underlying_symbol.upper(),
        symbol=contract.symbol,
        option_type=contract.option_type,
        expiration_date=contract.expiration_date,
        strike_price=contract.strike_price,
        bid_price=quote.bid_price,
        ask_price=quote.ask_price,
        limit_price=limit_price,
        contract_size=contract.contract_size,
        quantity=quantity,
        estimated_premium=estimated_premium,
        max_loss=estimated_premium,
        spread_pct=spread_pct,
        open_interest=contract.open_interest,
        delta=quote.delta,
    )
