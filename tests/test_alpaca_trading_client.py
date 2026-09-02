"""B17 — `workers/order_worker/alpaca_trading_client.py`. Frontière HTTP
mockée via `respx` (tiers externe, jamais notre infra) — même discipline
que `test_onboarding.py` (B07) pour `backend/app/alpaca_client.py`.

Nécessite `agents/`/`workers/` sur le path (ajoutés par conftest.py) —
sous `.venv-agents` comme le reste de la suite agents/workers (aucune
dépendance agents-only ici en réalité, seulement `httpx`, mais gardé
cohérent avec le reste de la suite B17)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

from order_worker.alpaca_trading_client import (  # noqa: E402
    AlpacaOrder,
    AlpacaOrderRejected,
    AlpacaTradingAuthError,
    AlpacaTradingClient,
    AlpacaTradingUpstreamError,
    _default_base_url,
)

BASE_URL = "https://paper-api.alpaca.markets"
ORDERS_URL = f"{BASE_URL}/v2/orders"


def _client() -> AlpacaTradingClient:
    return AlpacaTradingClient("fake-key", "fake-secret", base_url=BASE_URL)


def _order_json(*, order_id="alpaca-1", client_order_id="zst-1", status="accepted", symbol="AAPL") -> dict:
    return {
        "id": order_id,
        "client_order_id": client_order_id,
        "status": status,
        "symbol": symbol,
        "side": "buy",
        "submitted_at": "2026-09-01T12:00:00Z",
    }


class TestDefaultBaseUrl:
    def test_defaults_to_paper_api(self, monkeypatch):
        monkeypatch.delenv("ALPACA_PAPER_BASE_URL", raising=False)
        assert _default_base_url() == "https://paper-api.alpaca.markets"

    def test_reads_env_override(self, monkeypatch):
        monkeypatch.setenv("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets/custom")
        assert _default_base_url() == "https://paper-api.alpaca.markets/custom"


class TestPlaceOrder:
    def test_place_option_limit_order_sends_whole_qty_and_limit_price(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(return_value=httpx.Response(200, json=_order_json(symbol="AAPL260918C00200000")))
            client.place_order(
                symbol="AAPL260918C00200000",
                side="buy",
                client_order_id="zst-option-1",
                order_type="limit",
                time_in_force="day",
                qty=1,
                limit_price=3.10,
            )
            import json as _json

            body = _json.loads(mock.calls.last.request.content)
        assert body["qty"] == "1"
        assert body["limit_price"] == "3.10"
        assert "notional" not in body
        assert "order_class" not in body

    def test_place_market_order_sends_expected_body_and_headers(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(
                return_value=httpx.Response(200, headers={"x-request-id": "req-1"}, json=_order_json())
            )
            order = client.place_order(symbol="AAPL", side="buy", client_order_id="zst-1", qty=10)
            request = mock.calls.last.request

        assert request.headers["APCA-API-KEY-ID"] == "fake-key"
        assert request.headers["APCA-API-SECRET-KEY"] == "fake-secret"
        assert order == AlpacaOrder(
            id="alpaca-1", client_order_id="zst-1", status="accepted", symbol="AAPL", side="buy",
            submitted_at="2026-09-01T12:00:00Z", request_id="req-1", raw=_order_json(),
        )

    def test_place_bracket_order_includes_legs_and_order_class(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(return_value=httpx.Response(200, json=_order_json()))
            client.place_order(
                symbol="AAPL", side="buy", client_order_id="zst-1", notional=1000.0, order_class="bracket",
                take_profit={"limit_price": "156.00"}, stop_loss={"stop_price": "147.00"},
            )
            import json as _json

            body = _json.loads(mock.calls.last.request.content)

        assert body["order_class"] == "bracket"
        assert body["take_profit"] == {"limit_price": "156.00"}
        assert body["stop_loss"] == {"stop_price": "147.00"}
        assert body["notional"] == "1000.0"
        assert "qty" not in body

    def test_place_order_rejected_403_raises_with_message_and_code(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(
                return_value=httpx.Response(403, json={"code": 40310000, "message": "insufficient buying power"})
            )
            with pytest.raises(AlpacaOrderRejected) as exc_info:
                client.place_order(symbol="AAPL", side="buy", client_order_id="zst-1", qty=1)
        assert "insufficient buying power" in str(exc_info.value)
        assert exc_info.value.code == 40310000

    def test_place_order_rejected_422_raises(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(return_value=httpx.Response(422, json={"code": 42210000, "message": "symbole invalide"}))
            with pytest.raises(AlpacaOrderRejected):
                client.place_order(symbol="INVALID", side="buy", client_order_id="zst-1", qty=1)

    def test_place_order_409_duplicate_raises_rejected(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(return_value=httpx.Response(409, json={"message": "order already exists"}))
            with pytest.raises(AlpacaOrderRejected):
                client.place_order(symbol="AAPL", side="buy", client_order_id="zst-1", qty=1)

    def test_place_order_401_raises_auth_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(return_value=httpx.Response(401, json={"message": "unauthorized"}))
            with pytest.raises(AlpacaTradingAuthError):
                client.place_order(symbol="AAPL", side="buy", client_order_id="zst-1", qty=1)

    def test_place_order_500_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(return_value=httpx.Response(500, json={"message": "internal error"}))
            with pytest.raises(AlpacaTradingUpstreamError):
                client.place_order(symbol="AAPL", side="buy", client_order_id="zst-1", qty=1)

    def test_place_order_unreadable_response_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(return_value=httpx.Response(200, content=b"not json"))
            with pytest.raises(AlpacaTradingUpstreamError):
                client.place_order(symbol="AAPL", side="buy", client_order_id="zst-1", qty=1)

    def test_network_timeout_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.post(ORDERS_URL).mock(side_effect=httpx.TimeoutException("simulated timeout"))
            with pytest.raises(AlpacaTradingUpstreamError):
                client.place_order(symbol="AAPL", side="buy", client_order_id="zst-1", qty=1)


class TestCancelOrder:
    def test_cancel_order_204_succeeds(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.delete(f"{ORDERS_URL}/alpaca-1").mock(return_value=httpx.Response(204))
            client.cancel_order("alpaca-1")  # ne doit pas lever

    def test_cancel_order_unexpected_status_raises(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.delete(f"{ORDERS_URL}/alpaca-1").mock(return_value=httpx.Response(422, json={"message": "already filled"}))
            with pytest.raises(AlpacaOrderRejected):
                client.cancel_order("alpaca-1")


class TestReplaceOrder:
    def test_replace_order_sends_stringified_fields(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.patch(f"{ORDERS_URL}/alpaca-1").mock(return_value=httpx.Response(200, json=_order_json(status="replaced")))
            order = client.replace_order("alpaca-1", qty=5, limit_price=None)
            import json as _json

            body = _json.loads(mock.calls.last.request.content)
        assert body["qty"] == "5"
        assert body["limit_price"] is None
        assert order.status == "replaced"


class TestGetOrder:
    def test_get_order_returns_parsed_order(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{ORDERS_URL}/alpaca-1").mock(
                return_value=httpx.Response(200, headers={"x-request-id": "req-get"}, json=_order_json(status="fill"))
            )
            order = client.get_order("alpaca-1")
        assert order.status == "fill"
        assert order.request_id == "req-get"

    def test_get_order_not_found_raises_upstream_error(self):
        client = _client()
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{ORDERS_URL}/missing").mock(return_value=httpx.Response(404, json={"message": "order not found"}))
            with pytest.raises(AlpacaTradingUpstreamError):
                client.get_order("missing")
