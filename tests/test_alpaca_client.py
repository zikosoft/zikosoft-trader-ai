
from __future__ import annotations

import httpx
import pytest
import respx
from app.alpaca_client import (
    AlpacaAsset,
    AlpacaAuthError,
    AlpacaClient,
    AlpacaOptionContract,
    AlpacaOptionSnapshot,
    AlpacaPosition,
    AlpacaUpstreamError,
)
from app.config import settings

ACCOUNT_URL = f"{settings.alpaca_paper_base_url}/v2/account"
POSITIONS_URL = f"{settings.alpaca_paper_base_url}/v2/positions"
ASSETS_URL = f"{settings.alpaca_paper_base_url}/v2/assets"
OPTION_CONTRACTS_URL = f"{settings.alpaca_paper_base_url}/v2/options/contracts"
OPTION_CHAIN_URL = f"{settings.alpaca_data_base_url}/v1beta1/options/snapshots/AAPL"


def _asset_json(**overrides) -> dict:
    body = {
        "id": "asset-aapl",
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "class": "us_equity",
        "exchange": "NASDAQ",
        "status": "active",
        "tradable": True,
        "fractionable": True,
        "shortable": True,
    }
    body.update(overrides)
    return body


def _client() -> AlpacaClient:
    return AlpacaClient("fake-key", "fake-secret")


def _account_json(**overrides) -> dict:
    body = {
        "id": "alpaca-account-123",
        "account_number": "PA000TEST",
        "status": "ACTIVE",
        "currency": "USD",
        "cash": "98765.43",
        "portfolio_value": "150000.00",
        "buying_power": "197530.86",
        "equity": "150000.00",
        "last_equity": "149750.00",
    }
    body.update(overrides)
    return body


def _position_json(**overrides) -> dict:
    body = {
        "symbol": "AAPL",
        "qty": "10",
        "avg_entry_price": "150.00",
        "market_value": "1550.00",
        "unrealized_pl": "50.00",
        "current_price": "155.00",
        "side": "long",
    }
    body.update(overrides)
    return body


class TestGetAccountEquityFields:
    """§B18 — seul ce que B18 ajoute (`equity`/`last_equity`) est couvert
    ici ; le reste de `get_account()` (champs B07, codes d'erreur) est déjà
    couvert par `test_onboarding.py`."""

    def test_parses_equity_and_last_equity(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_json()))
            account = client.get_account()
        assert account.equity == "150000.00"
        assert account.last_equity == "149750.00"

    def test_missing_equity_fields_do_not_fail_parsing(self):
        """Tolérance délibérée (voir docstring d'`AlpacaAccount`) : un appelant
        qui n'a pas besoin d'`equity`/`last_equity` (onboarding.py) ne doit
        jamais échouer sur leur absence."""
        body = _account_json()
        del body["equity"]
        del body["last_equity"]
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ACCOUNT_URL).mock(return_value=httpx.Response(200, json=body))
            account = client.get_account()
        assert account.equity is None
        assert account.last_equity is None


class TestGetAssets:
    """§B09 — même discipline que `TestGetPositions` ci-dessous."""

    def test_returns_parsed_assets(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ASSETS_URL).mock(
                return_value=httpx.Response(
                    200, json=[_asset_json(), _asset_json(symbol="HALTED", tradable=False, fractionable=False, shortable=False)]
                )
            )
            assets = client.get_assets()
        assert assets == [
            AlpacaAsset(
                id="asset-aapl", symbol="AAPL", name="Apple Inc.", asset_class="us_equity",
                exchange="NASDAQ", status="active", tradable=True, fractionable=True, shortable=True,
            ),
            AlpacaAsset(
                id="asset-aapl", symbol="HALTED", name="Apple Inc.", asset_class="us_equity",
                exchange="NASDAQ", status="active", tradable=False, fractionable=False, shortable=False,
            ),
        ]

    def test_query_params_sent_correctly(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ASSETS_URL).mock(return_value=httpx.Response(200, json=[]))
            client.get_assets(status="inactive", asset_class="crypto")
            request = mock.calls.last.request
        assert request.url.params["status"] == "inactive"
        assert request.url.params["asset_class"] == "crypto"

    def test_empty_catalog_returns_empty_list(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ASSETS_URL).mock(return_value=httpx.Response(200, json=[]))
            assert client.get_assets() == []

    def test_401_raises_auth_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ASSETS_URL).mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
            with pytest.raises(AlpacaAuthError):
                client.get_assets()

    def test_500_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ASSETS_URL).mock(return_value=httpx.Response(500, json={"message": "internal error"}))
            with pytest.raises(AlpacaUpstreamError):
                client.get_assets()

    def test_non_list_response_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ASSETS_URL).mock(return_value=httpx.Response(200, json={"not": "a list"}))
            with pytest.raises(AlpacaUpstreamError):
                client.get_assets()

    def test_missing_field_raises_upstream_error(self):
        client = _client()
        body = _asset_json()
        del body["class"]
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ASSETS_URL).mock(return_value=httpx.Response(200, json=[body]))
            with pytest.raises(AlpacaUpstreamError):
                client.get_assets()

    def test_network_timeout_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ASSETS_URL).mock(side_effect=httpx.TimeoutException("simulated timeout"))
            with pytest.raises(AlpacaUpstreamError):
                client.get_assets()


class TestGetOptionContracts:
    def test_returns_contracts_and_sends_filters(self):
        client = _client()
        body = {
            "option_contracts": [
                {
                    "id": "contract-aapl-call",
                    "symbol": "AAPL260918C00200000",
                    "name": "AAPL Sep 18 2026 200 Call",
                    "status": "active",
                    "tradable": True,
                    "expiration_date": "2026-09-18",
                    "root_symbol": "AAPL",
                    "underlying_symbol": "AAPL",
                    "type": "call",
                    "strike_price": "200",
                    "size": "100",
                    "open_interest": "1200",
                    "close_price": "3.25",
                }
            ]
        }
        with respx.mock(assert_all_called=True) as mock:
            mock.get(OPTION_CONTRACTS_URL).mock(return_value=httpx.Response(200, json=body))
            contracts = client.get_option_contracts(
                underlying_symbol="aapl",
                expiration_date_gte="2026-09-10",
                option_type="call",
                strike_price_gte=190,
                strike_price_lte=210,
                limit=25,
            )
            request = mock.calls.last.request
        assert contracts == [
            AlpacaOptionContract(
                id="contract-aapl-call",
                symbol="AAPL260918C00200000",
                name="AAPL Sep 18 2026 200 Call",
                status="active",
                tradable=True,
                expiration_date="2026-09-18",
                root_symbol="AAPL",
                underlying_symbol="AAPL",
                option_type="call",
                strike_price="200",
                size=100,
                open_interest=1200,
                close_price="3.25",
            )
        ]
        assert request.url.params["underlying_symbols"] == "AAPL"
        assert request.url.params["type"] == "call"
        assert request.url.params["limit"] == "25"

    def test_auth_and_invalid_shape_are_reported(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(OPTION_CONTRACTS_URL).mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
            with pytest.raises(AlpacaAuthError):
                client.get_option_contracts(underlying_symbol="AAPL")
        with respx.mock(assert_all_called=True) as mock:
            mock.get(OPTION_CONTRACTS_URL).mock(return_value=httpx.Response(200, json=[]))
            with pytest.raises(AlpacaUpstreamError):
                client.get_option_contracts(underlying_symbol="AAPL")


class TestGetOptionChain:
    def test_parses_latest_quotes_and_greeks(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(OPTION_CHAIN_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "AAPL260918C00200000": {
                            "latestQuote": {"bp": 3.1, "ap": 3.3, "bs": 10, "as": 12},
                            "latestTrade": {"p": 3.2},
                            "greeks": {"delta": 0.52, "gamma": 0.03, "theta": -0.02, "vega": 0.11, "impliedVolatility": 0.24},
                        }
                    },
                )
            )
            snapshots = client.get_option_chain(underlying_symbol="aapl", option_type="call", limit=10)
            request = mock.calls.last.request
        assert snapshots == [
            AlpacaOptionSnapshot(
                symbol="AAPL260918C00200000",
                bid_price=3.1,
                ask_price=3.3,
                last_trade_price=3.2,
                bid_size=10,
                ask_size=12,
                implied_volatility=0.24,
                delta=0.52,
                gamma=0.03,
                theta=-0.02,
                vega=0.11,
            )
        ]
        assert request.url.params["type"] == "call"
        assert request.url.params["limit"] == "10"

    def test_network_error_is_wrapped(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(OPTION_CHAIN_URL).mock(return_value=httpx.Response(500, json={"message": "error"}))
            with pytest.raises(AlpacaUpstreamError):
                client.get_option_chain(underlying_symbol="AAPL")


class TestGetPositions:
    def test_returns_parsed_positions(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(
                return_value=httpx.Response(200, json=[_position_json(), _position_json(symbol="MSFT", side="short")])
            )
            positions = client.get_positions()
        assert positions == [
            AlpacaPosition(
                symbol="AAPL", qty="10", avg_entry_price="150.00", market_value="1550.00",
                unrealized_pl="50.00", current_price="155.00", side="long",
            ),
            AlpacaPosition(
                symbol="MSFT", qty="10", avg_entry_price="150.00", market_value="1550.00",
                unrealized_pl="50.00", current_price="155.00", side="short",
            ),
        ]

    def test_no_open_positions_returns_empty_list(self):
        """Alpaca renvoie `[]` (200), jamais une erreur, quand aucune
        position n'est ouverte — voir docstring de `get_positions()`."""
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(200, json=[]))
            assert client.get_positions() == []

    def test_headers_sent_correctly(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(200, json=[]))
            client.get_positions()
            request = mock.calls.last.request
        assert request.headers["APCA-API-KEY-ID"] == "fake-key"
        assert request.headers["APCA-API-SECRET-KEY"] == "fake-secret"

    def test_401_raises_auth_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
            with pytest.raises(AlpacaAuthError):
                client.get_positions()

    def test_500_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(500, json={"message": "internal error"}))
            with pytest.raises(AlpacaUpstreamError):
                client.get_positions()

    def test_non_list_response_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(200, json={"not": "a list"}))
            with pytest.raises(AlpacaUpstreamError):
                client.get_positions()

    def test_missing_field_raises_upstream_error(self):
        client = _client()
        body = _position_json()
        del body["avg_entry_price"]
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(200, json=[body]))
            with pytest.raises(AlpacaUpstreamError):
                client.get_positions()

    def test_network_timeout_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(side_effect=httpx.TimeoutException("simulated timeout"))
            with pytest.raises(AlpacaUpstreamError):
                client.get_positions()
