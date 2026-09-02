from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from shared.options import OptionSelectionError, OptionSelectionPolicy, select_option_contract
from shared.order_command import OrderCommand


def _contract(symbol: str, option_type: str, strike: float, expiration: str = "2026-09-18") -> dict:
    return {
        "symbol": symbol,
        "underlying_symbol": "AAPL",
        "option_type": option_type,
        "expiration_date": expiration,
        "strike_price": strike,
        "tradable": True,
        "status": "active",
        "contract_size": 100,
        "open_interest": 500,
    }


def _quote(symbol: str, bid: float, ask: float, delta: float) -> dict:
    return {"symbol": symbol, "bid_price": bid, "ask_price": ask, "delta": delta}


class TestSelectOptionContract:
    def test_buy_selects_liquid_atm_call_and_computes_max_loss(self):
        call = _contract("AAPL260918C00200000", "call", 200)
        put = _contract("AAPL260918P00200000", "put", 200)
        selected = select_option_contract(
            signal="BUY",
            underlying_price=201,
            contracts=[call, put],
            quotes={
                call["symbol"]: _quote(call["symbol"], 2.90, 3.10, 0.52),
                put["symbol"]: _quote(put["symbol"], 2.80, 3.00, -0.48),
            },
            as_of=date(2026, 9, 1),
        )
        assert selected is not None
        assert selected.symbol == call["symbol"]
        assert selected.option_type == "call"
        assert selected.quantity == 1
        assert selected.limit_price == 3.10
        assert selected.estimated_premium == 310.0
        assert selected.max_loss == 310.0

    def test_sell_selects_put_and_hold_creates_no_instrument(self):
        put = _contract("AAPL260918P00200000", "put", 200)
        quote = _quote(put["symbol"], 2.0, 2.2, -0.5)
        assert select_option_contract(signal="HOLD", underlying_price=200, contracts=[put], quotes=[quote], as_of=date(2026, 9, 1)) is None
        selected = select_option_contract(signal="SELL", underlying_price=200, contracts=[put], quotes=[quote], as_of=date(2026, 9, 1))
        assert selected is not None
        assert selected.option_type == "put"

    def test_rejects_wide_spread_and_premium_above_cap(self):
        call = _contract("AAPL260918C00200000", "call", 200)
        with pytest.raises(OptionSelectionError):
            select_option_contract(signal="BUY", underlying_price=200, contracts=[call], quotes=[_quote(call["symbol"], 1.0, 2.0, 0.5)], as_of=date(2026, 9, 1))
        with pytest.raises(OptionSelectionError):
            select_option_contract(signal="BUY", underlying_price=200, contracts=[call], quotes=[_quote(call["symbol"], 10.0, 10.1, 0.5)], as_of=date(2026, 9, 1), policy=OptionSelectionPolicy(max_premium=500))


class TestOptionOrderCommand:
    def _payload(self) -> dict:
        call = _contract("AAPL260918C00200000", "call", 200)
        selected = select_option_contract(signal="BUY", underlying_price=200, contracts=[call], quotes=[_quote(call["symbol"], 3.0, 3.1, 0.5)], as_of=date(2026, 9, 1))
        return {
            "strategy_id": "00000000-0000-0000-0000-000000000001",
            "risk_decision_id": "00000000-0000-0000-0000-000000000002",
            "agent_decision_id": "00000000-0000-0000-0000-000000000003",
            "explanation_agent_decision_id": "00000000-0000-0000-0000-000000000004",
            "symbol": selected.symbol,
            "side": "buy",
            "asset_class": "option",
            "order_type": "limit",
            "time_in_force": "day",
            "reference_price": selected.limit_price,
            "quantity": selected.quantity,
            "sizing_pending": False,
            "option_instrument": selected.model_dump(mode="json"),
        }

    def test_valid_option_command_is_explicit_and_long_only(self):
        command = OrderCommand(**self._payload())
        assert command.asset_class == "option"
        assert command.option_instrument.option_type == "call"

    @pytest.mark.parametrize("overrides", [{"side": "sell"}, {"order_type": "market"}, {"notional": 100}, {"sizing_pending": True}, {"quantity": 2}])
    def test_rejects_unsafe_option_command(self, overrides):
        payload = self._payload()
        payload.update(overrides)
        with pytest.raises(ValidationError):
            OrderCommand(**payload)
