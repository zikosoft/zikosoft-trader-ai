"""B17 — `workers/order_worker/trade_updates_listener.py`. Deux
catégories de tests, même principe que `test_mcp_session.py` (B10) pour
`McpSessionManager` :

1. Pures (`parse_trade_update`, `_is_auth_success`) : aucune connexion,
   aucun thread.
2. `TestTradeUpdatesListenerUnit` : `connection_factory` injecté par un
   double contrôlable (`_ScriptedConnectionFactory`/`_FakeConnection`) —
   panne de connexion, échec d'authentification, coupure en cours de
   réception, reconnexion, testés de façon déterministe, sans dépendre du
   vrai WebSocket Alpaca (inaccessible depuis cette sandbox, voir
   docstring du module testé).

Nécessite `agents/`/`workers/` sur le path (ajoutés par conftest.py) et
`websockets` (agents/requirements.txt) — sous `.venv-agents`, comme le
reste de la suite agents/workers."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

pytest.importorskip("websockets", reason="suite agents/workers — lancer avec `make test-agents` (.venv-agents)")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workers"))

from order_worker.trade_updates_listener import (  # noqa: E402
    STATUS_HEALTHY,
    STATUS_RECONNECTING,
    STATUS_STOPPED,
    TradeUpdatesListener,
    TradeUpdatesListenerError,
    _is_auth_success,
    parse_trade_update,
)

AUTH_OK = json.dumps({"stream": "authorization", "data": {"status": "authorized", "action": "authenticate"}})
AUTH_FAILED = json.dumps({"stream": "authorization", "data": {"status": "unauthorized", "action": "authenticate"}})


def _fill_event(order_id: str = "order-1") -> str:
    return json.dumps({"stream": "trade_updates", "data": {"event": "fill", "order": {"id": order_id, "client_order_id": "zst-1"}}})


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition jamais atteinte avant le délai")


def _wait_for_status(listener: TradeUpdatesListener, status: str, *, timeout: float = 5.0) -> None:
    _wait_until(lambda: listener.health().status == status, timeout=timeout)


_HEARTBEAT = json.dumps({"stream": "authorization", "data": {"status": "authorized"}})


class _FakeConnection:
    """Double contrôlable d'une connexion WebSocket — 1er `recv()` renvoie
    la réponse d'authentification, les suivants renvoient `messages` dans
    l'ordre. Une fois `messages` épuisés : soit une coupure simulée
    (`drop_after_messages=True`, lève `ConnectionError`), soit — par
    défaut — un "heartbeat" inoffensif (ignoré par `parse_trade_update`,
    pas un événement `trade_updates`) renvoyé en boucle, pour que la
    connexion reste "vivante" tant que le test ne l'a pas explicitement
    arrêtée (`listener.stop()`) plutôt que de déclencher une reconnexion
    en boucle non désirée par le test."""

    def __init__(self, *, auth_response: str = AUTH_OK, messages: list[str] | None = None, drop_after_messages: bool = False) -> None:
        self.auth_response = auth_response
        self.messages = list(messages or [])
        self.drop_after_messages = drop_after_messages
        self.sent: list[str] = []
        self._recv_calls = 0

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        self._recv_calls += 1
        if self._recv_calls == 1:
            return self.auth_response
        idx = self._recv_calls - 2
        if idx < len(self.messages):
            return self.messages[idx]
        if self.drop_after_messages:
            raise ConnectionError("simulated: connexion coupée")
        await asyncio.sleep(0.005)
        return _HEARTBEAT


class _ScriptedConnectionFactory:
    """Fabrique de connexion injectée — même motif que `_ScriptedFactory`
    dans `test_mcp_session.py` (B10) pour `McpSessionManager`. Chaque appel
    consomme l'entrée suivante du script (connexion à retourner, ou
    exception à lever pour simuler un échec de connexion) ; reste sur la
    dernière entrée une fois le script épuisé."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.call_count = 0

    def __call__(self, url: str):
        self.call_count += 1
        entry = self._script[min(self.call_count - 1, len(self._script) - 1)]

        @asynccontextmanager
        async def _ctx():
            if isinstance(entry, Exception):
                raise entry
            yield entry

        return _ctx()


# ----------------------------------------------------------------------
# Fonctions pures
# ----------------------------------------------------------------------


class TestParseTradeUpdate:
    def test_valid_fill_event(self):
        parsed = parse_trade_update(_fill_event())
        assert parsed["event"] == "fill"
        assert parsed["order"]["id"] == "order-1"

    def test_wrong_stream_returns_none(self):
        assert parse_trade_update(json.dumps({"stream": "authorization", "data": {}})) is None

    def test_malformed_json_returns_none(self):
        assert parse_trade_update("not json{{{") is None

    def test_missing_event_or_order_returns_none(self):
        assert parse_trade_update(json.dumps({"stream": "trade_updates", "data": {"event": "fill"}})) is None
        assert parse_trade_update(json.dumps({"stream": "trade_updates", "data": {"order": {}}})) is None

    def test_unknown_event_type_returns_none(self):
        payload = json.dumps({"stream": "trade_updates", "data": {"event": "not_a_real_alpaca_event", "order": {}}})
        assert parse_trade_update(payload) is None

    def test_non_dict_json_returns_none(self):
        assert parse_trade_update(json.dumps([1, 2, 3])) is None


class TestIsAuthSuccess:
    def test_authorized(self):
        assert _is_auth_success(AUTH_OK) is True

    def test_unauthorized(self):
        assert _is_auth_success(AUTH_FAILED) is False

    def test_malformed(self):
        assert _is_auth_success("not json") is False


# ----------------------------------------------------------------------
# TradeUpdatesListener — double injecté, aucun réseau réel.
# ----------------------------------------------------------------------


class TestTradeUpdatesListenerUnit:
    def test_connects_authenticates_subscribes_and_receives_events(self):
        events = []
        conn = _FakeConnection(messages=[_fill_event()])
        factory = _ScriptedConnectionFactory([conn])
        listener = TradeUpdatesListener(on_event=events.append, connection_factory=factory, backoff_schedule=(0.05,))
        try:
            listener.start("fake-key", "fake-secret")
            _wait_for_status(listener, STATUS_HEALTHY)
            _wait_until(lambda: len(events) >= 1)
            assert events[0]["event"] == "fill"
            assert json.loads(conn.sent[0]) == {"action": "auth", "key": "fake-key", "secret": "fake-secret"}
            assert json.loads(conn.sent[1]) == {"action": "listen", "data": {"streams": ["trade_updates"]}}
        finally:
            listener.stop()
        assert listener.health().status == STATUS_STOPPED

    def test_auth_failure_triggers_reconnect_until_success(self):
        bad_conn = _FakeConnection(auth_response=AUTH_FAILED)
        good_conn = _FakeConnection(messages=[_fill_event()])
        factory = _ScriptedConnectionFactory([bad_conn, good_conn])
        listener = TradeUpdatesListener(on_event=lambda e: None, connection_factory=factory, backoff_schedule=(0.05,))
        try:
            listener.start("k", "s")
            _wait_for_status(listener, STATUS_HEALTHY, timeout=5.0)
            assert listener.health().reconnect_count >= 1
            assert factory.call_count >= 2
        finally:
            listener.stop()

    def test_connection_failure_before_any_success_does_not_call_on_reconnected(self):
        """Une panne AVANT toute connexion réussie n'est pas une
        "reconnexion" (rien à réconcilier) — `on_reconnected` ne doit
        jamais être appelé dans ce cas, seulement après une PREMIÈRE
        connexion déjà établie avec succès (voir docstring du module)."""
        reconnected_calls = []
        good_conn = _FakeConnection(messages=[_fill_event()])
        factory = _ScriptedConnectionFactory([ConnectionRefusedError("simulated: server not ready"), good_conn])
        listener = TradeUpdatesListener(
            on_event=lambda e: None, on_reconnected=lambda: reconnected_calls.append(1), connection_factory=factory, backoff_schedule=(0.05,)
        )
        try:
            listener.start("k", "s")
            _wait_for_status(listener, STATUS_HEALTHY, timeout=5.0)
            time.sleep(0.1)
            assert reconnected_calls == []
        finally:
            listener.stop()

    def test_on_reconnected_fires_only_after_a_prior_successful_connection(self):
        """§checklist "WebSocket coupé puis restauré" : la 1re connexion
        réussit puis est coupée (plus de messages -> `ConnectionError`
        simulée) ; à la reconnexion, `on_reconnected` doit être appelé
        AVANT de reprendre la réception d'événements."""
        reconnected_calls = []
        events = []
        first_conn = _FakeConnection(messages=[], drop_after_messages=True)  # succès, puis coupure immédiate
        second_conn = _FakeConnection(messages=[_fill_event()])
        factory = _ScriptedConnectionFactory([first_conn, second_conn])
        listener = TradeUpdatesListener(
            on_event=events.append, on_reconnected=lambda: reconnected_calls.append(1), connection_factory=factory, backoff_schedule=(0.05,)
        )
        try:
            listener.start("k", "s")
            _wait_until(lambda: len(events) >= 1, timeout=5.0)
            assert reconnected_calls == [1]
            assert events[0]["event"] == "fill"
        finally:
            listener.stop()

    def test_on_event_exception_does_not_kill_the_connection(self):
        events = []

        def _raising_on_event(event):
            events.append(event)
            raise RuntimeError("simulated: callback failure")

        conn = _FakeConnection(messages=[_fill_event(), _fill_event(order_id="order-2")])
        factory = _ScriptedConnectionFactory([conn])
        listener = TradeUpdatesListener(on_event=_raising_on_event, connection_factory=factory, backoff_schedule=(0.05,))
        try:
            listener.start("k", "s")
            _wait_until(lambda: len(events) >= 2, timeout=5.0)
        finally:
            listener.stop()

    def test_stop_is_clean_and_idempotent(self):
        conn = _FakeConnection(messages=[], drop_after_messages=True)
        factory = _ScriptedConnectionFactory([conn])
        listener = TradeUpdatesListener(on_event=lambda e: None, connection_factory=factory, backoff_schedule=(0.05,))
        listener.start("k", "s")
        _wait_for_status(listener, STATUS_RECONNECTING, timeout=5.0)  # coupure immédiate (aucun message)
        listener.stop()
        assert listener.health().status == STATUS_STOPPED
        listener.stop()  # idempotent — ne doit pas lever
        assert listener.health().status == STATUS_STOPPED

    def test_start_twice_is_a_noop_while_already_running(self):
        conn = _FakeConnection(messages=[_fill_event()])
        factory = _ScriptedConnectionFactory([conn])
        listener = TradeUpdatesListener(on_event=lambda e: None, connection_factory=factory, backoff_schedule=(0.05,))
        try:
            listener.start("k", "s")
            _wait_for_status(listener, STATUS_HEALTHY)
            listener.start("k", "s")  # ne doit pas relancer un deuxième thread/une deuxième connexion
            time.sleep(0.1)
            assert factory.call_count == 1
        finally:
            listener.stop()


def test_trade_updates_listener_error_is_a_plain_exception():
    with pytest.raises(TradeUpdatesListenerError):
        raise TradeUpdatesListenerError("authentification refusée")
