"""Regression tests for MCP list/envelope normalization used by Paper options."""

from shared.options import normalize_option_contracts, normalize_option_quotes


def test_contracts_accept_mcp_raw_value_list():
    contracts = normalize_option_contracts(
        {
            "raw_value": [
                {
                    "symbol": "DELL260918C00130000",
                    "underlying_symbol": "DELL",
                    "type": "call",
                    "expiration_date": "2026-09-18",
                    "strike_price": "130",
                    "tradable": True,
                    "status": "active",
                }
            ]
        },
        underlying_symbol="DELL",
    )

    assert contracts == [
        {
            "symbol": "DELL260918C00130000",
            "underlying_symbol": "DELL",
            "option_type": "call",
            "expiration_date": "2026-09-18",
            "strike_price": "130",
            "tradable": True,
            "status": "active",
            "contract_size": 100,
            "open_interest": None,
        }
    ]


def test_quotes_accept_mcp_raw_value_snapshot_mapping():
    quotes = normalize_option_quotes(
        {
            "raw_value": {
                "DELL260918C00130000": {
                    "latestQuote": {"bp": 2.0, "ap": 2.2},
                    "greeks": {"delta": 0.5},
                }
            }
        }
    )

    assert quotes["DELL260918C00130000"]["bid_price"] == 2.0
    assert quotes["DELL260918C00130000"]["ask_price"] == 2.2
    assert quotes["DELL260918C00130000"]["delta"] == 0.5
