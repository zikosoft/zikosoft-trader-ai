
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

from portfolio_worker.alpaca_portfolio_client import (  # noqa: E402
    AlpacaAccountSnapshot,
    AlpacaPortfolioAuthError,
    AlpacaPortfolioClient,
    AlpacaPortfolioUpstreamError,
    AlpacaPositionSnapshot,
    _default_base_url,
)

BASE_URL = "https://paper-api.alpaca.markets"
ACCOUNT_URL = f"{BASE_URL}/v2/account"
POSITIONS_URL = f"{BASE_URL}/v2/positions"


def _client() -> AlpacaPortfolioClient:
    return AlpacaPortfolioClient("fake-key", "fake-secret", base_url=BASE_URL)


def _account_json(**overrides) -> dict:
    body = {
        "cash": "50000.00",
        "buying_power": "100000.00",
        "portfolio_value": "150000.00",
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
    }
    body.update(overrides)
    return body


class TestDefaultBaseUrl:
    def test_defaults_to_paper_api(self, monkeypatch):
        monkeypatch.delenv("ALPACA_PAPER_BASE_URL", raising=False)
        assert _default_base_url() == "https://paper-api.alpaca.markets"

    def test_reads_env_override(self, monkeypatch):
        monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets/custom")
        assert _default_base_url() == "https://paper-api.alpaca.markets/custom"


class TestGetAccount:
    def test_parses_expected_fields_and_sends_headers(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ACCOUNT_URL).mock(return_value=httpx.Response(200, json=_account_json()))
            account = client.get_account()
            request = mock.calls.last.request
        assert request.headers["APCA-API-KEY-ID"] == "fake-key"
        assert request.headers["APCA-API-SECRET-KEY"] == "fake-secret"
        assert account == AlpacaAccountSnapshot(
            cash="50000.00", buying_power="100000.00", portfolio_value="150000.00",
            equity="150000.00", last_equity="149750.00",
        )

    def test_missing_equity_fields_tolerated(self):
        body = _account_json()
        del body["equity"]
        del body["last_equity"]
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ACCOUNT_URL).mock(return_value=httpx.Response(200, json=body))
            account = client.get_account()
        assert account.equity is None
        assert account.last_equity is None

    def test_401_raises_auth_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ACCOUNT_URL).mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
            with pytest.raises(AlpacaPortfolioAuthError):
                client.get_account()

    def test_500_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ACCOUNT_URL).mock(return_value=httpx.Response(500, json={"message": "internal error"}))
            with pytest.raises(AlpacaPortfolioUpstreamError):
                client.get_account()

    def test_missing_required_field_raises_upstream_error(self):
        body = _account_json()
        del body["cash"]
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ACCOUNT_URL).mock(return_value=httpx.Response(200, json=body))
            with pytest.raises(AlpacaPortfolioUpstreamError):
                client.get_account()

    def test_timeout_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(ACCOUNT_URL).mock(side_effect=httpx.TimeoutException("simulated timeout"))
            with pytest.raises(AlpacaPortfolioUpstreamError):
                client.get_account()


class TestGetPositions:
    def test_returns_parsed_positions(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(
                return_value=httpx.Response(200, json=[_position_json(), _position_json(symbol="MSFT")])
            )
            positions = client.get_positions()
        assert positions == [
            AlpacaPositionSnapshot(
                symbol="AAPL", qty="10", avg_entry_price="150.00", market_value="1550.00", unrealized_pl="50.00"
            ),
            AlpacaPositionSnapshot(
                symbol="MSFT", qty="10", avg_entry_price="150.00", market_value="1550.00", unrealized_pl="50.00"
            ),
        ]

    def test_no_open_positions_returns_empty_list(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(200, json=[]))
            assert client.get_positions() == []

    def test_401_raises_auth_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
            with pytest.raises(AlpacaPortfolioAuthError):
                client.get_positions()

    def test_non_list_response_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(200, json={"not": "a list"}))
            with pytest.raises(AlpacaPortfolioUpstreamError):
                client.get_positions()

    def test_missing_field_raises_upstream_error(self):
        body = _position_json()
        del body["market_value"]
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(POSITIONS_URL).mock(return_value=httpx.Response(200, json=[body]))
            with pytest.raises(AlpacaPortfolioUpstreamError):
                client.get_positions()
