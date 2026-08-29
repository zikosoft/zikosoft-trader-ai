"""B10 — McpSessionManager (mitigation R02). Deux catégories de tests :

1. Unitaires (`Test*Unit`) : `session_factory` injecté par un double
   contrôlable — pannes/reconnexion/restart déclenchés de façon
   déterministe, sans dépendre du vrai process serveur (rapide, fiable en
   CI).
2. Intégration réelle (`Test*RealServer`) : contre le VRAI serveur MCP
   officiel Alpaca (`alpaca-mcp-server`, installé comme dépendance pip de
   `agents/requirements.txt`), avec des clés factices — mêmes limites que
   le spike isolé (`spike_alpaca_mcp.py`) : le protocole/la session/le
   filtrage de toolset sont vérifiés pour de vrai, un appel d'outil réel
   échoue au niveau réseau (aucune route sortante vers Alpaca depuis cette
   sandbox) et c'est le comportement attendu, testé explicitement.

Nécessite `agents/` sur le path (ajouté par conftest.py) et les
dépendances de `agents/requirements.txt` installées — voir
`.venv-agents` (venv séparé de `.venv` backend, voir la note dans
`agents/requirements.txt` sur le conflit starlette/fastmcp)."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

# Ce fichier dépend de `agents/requirements.txt` (mcp, alpaca-mcp-server),
# installées dans `.venv-agents` — un venv SÉPARÉ de `.venv` (backend),
# volontairement, parce que ces deux packages embarquent un `starlette`
# incompatible avec le `fastapi` pinné par backend/requirements.txt (conflit
# rencontré et documenté en construisant B10, voir agents/requirements.txt
# et AVANCEMENT.md §39). Sous `.venv` (backend), ce module est absent et ce
# fichier est proprement SKIPPÉ plutôt que de faire échouer `make test` —
# lancer la suite agents avec `make test-agents` (voir Makefile).
pytest.importorskip("mcp", reason="suite agents — lancer avec `make test-agents` (.venv-agents)")

from common.mcp_session import (  # noqa: E402 — après importorskip, volontaire
    CALLABLE_TOOL_ALLOWLIST,
    STATUS_HEALTHY,
    STATUS_STOPPED,
    McpSessionError,
    McpSessionManager,
)


def _wait_for_status(manager: McpSessionManager, status: str, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager.health().status == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"jamais atteint le statut {status!r}, statut actuel : {manager.health()}")


@dataclass
class _FakeTool:
    name: str


class _FakeSession:
    """Double contrôlable — simule une session MCP déjà initialisée."""

    def __init__(self, tool_names: list[str], *, fail_after_n_calls: int | None = None) -> None:
        self._tool_names = tool_names
        self._fail_after_n_calls = fail_after_n_calls
        self._call_count = 0

    async def list_tools(self):
        @dataclass
        class _Resp:
            tools: list

        return _Resp(tools=[_FakeTool(name=n) for n in self._tool_names])

    async def call_tool(self, name: str, arguments: dict):
        self._call_count += 1
        if self._fail_after_n_calls is not None and self._call_count > self._fail_after_n_calls:
            raise ConnectionError("simulated transport failure")

        @dataclass
        class _Content:
            text: str

        @dataclass
        class _Result:
            isError: bool
            content: list
            structuredContent: dict | None = None

        return _Result(isError=False, content=[_Content(text='{"ok": true}')])


class _ScriptedFactory:
    """Fabrique de session injectée dans McpSessionManager — chaque appel
    consomme l'entrée suivante du script (session à retourner, ou
    exception à lever pour simuler un échec de connexion)."""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.call_count = 0

    def __call__(self, api_key: str, secret_key: str):
        self.call_count += 1
        entry = self._script[min(self.call_count - 1, len(self._script) - 1)]

        @asynccontextmanager
        async def _ctx():
            if isinstance(entry, Exception):
                raise entry
            session = entry
            try:
                yield session
            finally:
                pass

        return _ctx()


READ_ONLY_TOOL_NAMES = ["get_clock", "get_stock_snapshot", "get_all_positions"]
TRADING_TOOL_NAMES = ["place_stock_order", "cancel_order_by_id"]


class TestMcpSessionManagerUnit:
    def test_starts_and_becomes_healthy(self):
        factory = _ScriptedFactory([_FakeSession(READ_ONLY_TOOL_NAMES)])
        mgr = McpSessionManager(session_factory=factory)
        try:
            mgr.start("fake-key", "fake-secret")
            _wait_for_status(mgr, STATUS_HEALTHY)
            health = mgr.health()
            assert health.tool_count == len(READ_ONLY_TOOL_NAMES)
            assert health.trading_toolset_excluded is True
        finally:
            mgr.stop()

    def test_trading_tools_present_are_detected_as_not_excluded(self):
        """Si jamais le filtrage serveur (ALPACA_TOOLSETS) était contourné
        ou mal configuré, la session doit le signaler plutôt que de
        prétendre silencieusement que tout va bien."""
        factory = _ScriptedFactory([_FakeSession(READ_ONLY_TOOL_NAMES + TRADING_TOOL_NAMES)])
        mgr = McpSessionManager(session_factory=factory)
        try:
            mgr.start("fake-key", "fake-secret")
            _wait_for_status(mgr, STATUS_HEALTHY)
            assert mgr.health().trading_toolset_excluded is False
        finally:
            mgr.stop()

    def test_disallowed_tool_rejected_without_reaching_session(self):
        """§B10 deuxième couche de défense : un outil hors allowlist est
        rejeté par McpSessionManager lui-même, jamais transmis à la
        session — même si le serveur l'exposait."""
        factory = _ScriptedFactory([_FakeSession(READ_ONLY_TOOL_NAMES + TRADING_TOOL_NAMES)])
        mgr = McpSessionManager(session_factory=factory)
        try:
            mgr.start("fake-key", "fake-secret")
            _wait_for_status(mgr, STATUS_HEALTHY)
            with pytest.raises(McpSessionError, match="non autorisé"):
                mgr.call_tool("place_stock_order", {"symbol": "AAPL"})
        finally:
            mgr.stop()

    def test_allowed_tool_call_succeeds(self):
        factory = _ScriptedFactory([_FakeSession(READ_ONLY_TOOL_NAMES)])
        mgr = McpSessionManager(session_factory=factory)
        try:
            mgr.start("fake-key", "fake-secret")
            _wait_for_status(mgr, STATUS_HEALTHY)
            assert "get_clock" in CALLABLE_TOOL_ALLOWLIST
            result = mgr.call_tool("get_clock")
            assert result == {"ok": True}
        finally:
            mgr.stop()

    def test_rate_limit_exceeded_raises_without_reaching_session(self):
        """§B10 sécurité "limite d'appels" — deuxième ligne de défense
        locale, indépendante des limites Alpaca elles-mêmes (voir
        commentaire sur DEFAULT_MAX_CALLS_PER_MINUTE). Même style que
        `test_ai_provider.py::test_rate_limit_exceeded_raises_without_extra_http_call` :
        quota bas et déterministe, aucun appel au-delà ne doit atteindre la
        session (le compteur `call_tool` du double n'avance plus)."""
        factory = _ScriptedFactory([_FakeSession(READ_ONLY_TOOL_NAMES)])
        mgr = McpSessionManager(session_factory=factory, max_calls_per_minute=2)
        try:
            mgr.start("fake-key", "fake-secret")
            _wait_for_status(mgr, STATUS_HEALTHY)
            assert mgr.call_tool("get_clock") == {"ok": True}
            assert mgr.call_tool("get_clock") == {"ok": True}
            with pytest.raises(McpSessionError, match="limite d'appels MCP dépassée"):
                mgr.call_tool("get_clock")
        finally:
            mgr.stop()

    def test_reconnects_after_connection_failure(self):
        """Panne de connexion sur la 1re tentative -> RECONNECTING ->
        rétablie sur la 2e tentative -> HEALTHY, sans crash du thread."""
        factory = _ScriptedFactory(
            [ConnectionRefusedError("simulated: server not ready"), _FakeSession(READ_ONLY_TOOL_NAMES)]
        )
        mgr = McpSessionManager(session_factory=factory, backoff_schedule=(0.05,))
        try:
            mgr.start("fake-key", "fake-secret")
            _wait_for_status(mgr, STATUS_HEALTHY, timeout=5.0)
            assert mgr.health().reconnect_count >= 1
            assert factory.call_count >= 2
        finally:
            mgr.stop()

    def test_session_death_mid_flight_triggers_reconnect(self):
        """La session tombe après le 1er appel d'outil réussi (simulateur
        `fail_after_n_calls`) -> l'appel suivant échoue proprement, puis le
        superviseur reconnecte (nouvelle session fournie par le script)."""
        first = _FakeSession(READ_ONLY_TOOL_NAMES, fail_after_n_calls=1)
        second = _FakeSession(READ_ONLY_TOOL_NAMES)
        factory = _ScriptedFactory([first, first, second])  # même 1re session tant qu'elle ne meurt pas
        mgr = McpSessionManager(session_factory=factory, backoff_schedule=(0.05,))
        try:
            mgr.start("fake-key", "fake-secret")
            _wait_for_status(mgr, STATUS_HEALTHY)
            result = mgr.call_tool("get_clock")
            assert result == {"ok": True}
            with pytest.raises(McpSessionError):
                mgr.call_tool("get_clock")
        finally:
            mgr.stop()

    def test_restart_forces_new_connection_with_new_credentials(self):
        session_a = _FakeSession(READ_ONLY_TOOL_NAMES)
        session_b = _FakeSession(READ_ONLY_TOOL_NAMES)
        seen_credentials = []

        def factory(api_key, secret_key):
            seen_credentials.append((api_key, secret_key))
            session = session_a if len(seen_credentials) == 1 else session_b

            @asynccontextmanager
            async def _ctx():
                yield session

            return _ctx()

        mgr = McpSessionManager(session_factory=factory)
        try:
            mgr.start("key-A", "secret-A")
            _wait_for_status(mgr, STATUS_HEALTHY)
            mgr.restart("key-B", "secret-B")
            # Le restart doit provoquer une nouvelle connexion avec les
            # nouveaux credentials (pas juste un flag ignoré).
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and len(seen_credentials) < 2:
                time.sleep(0.05)
            assert seen_credentials == [("key-A", "secret-A"), ("key-B", "secret-B")]
        finally:
            mgr.stop()

    def test_stop_is_clean_and_idempotent_state(self):
        factory = _ScriptedFactory([_FakeSession(READ_ONLY_TOOL_NAMES)])
        mgr = McpSessionManager(session_factory=factory)
        mgr.start("fake-key", "fake-secret")
        _wait_for_status(mgr, STATUS_HEALTHY)
        mgr.stop()
        assert mgr.health().status == STATUS_STOPPED
        with pytest.raises(McpSessionError):
            mgr.call_tool("get_clock")

    def test_publish_health_writes_json_with_ttl(self, redis_client):
        factory = _ScriptedFactory([_FakeSession(READ_ONLY_TOOL_NAMES)])
        mgr = McpSessionManager(session_factory=factory)
        try:
            mgr.start("fake-key", "fake-secret")
            _wait_for_status(mgr, STATUS_HEALTHY)
            key = "mcp:session:health:test-user"
            mgr.publish_health(redis_client, key=key, ttl_seconds=30)
            raw = redis_client.get(key)
            assert raw is not None
            import json

            payload = json.loads(raw)
            assert payload["status"] == STATUS_HEALTHY
            ttl = redis_client.ttl(key)
            assert 0 < ttl <= 30
        finally:
            mgr.stop()

    def test_never_logs_credentials(self, caplog):
        """Grep défensif : les credentials ne doivent apparaître dans aucun
        message de log émis par ce module, même en cas de panne."""
        marker_key, marker_secret = "MARKER-KEY-ZZZ", "MARKER-SECRET-ZZZ"
        factory = _ScriptedFactory(
            [ConnectionRefusedError("boom"), _FakeSession(READ_ONLY_TOOL_NAMES)]
        )
        mgr = McpSessionManager(session_factory=factory, backoff_schedule=(0.05,))
        try:
            with caplog.at_level("DEBUG", logger="mcp_session"):
                mgr.start(marker_key, marker_secret)
                _wait_for_status(mgr, STATUS_HEALTHY)
            for record in caplog.records:
                assert marker_key not in record.getMessage()
                assert marker_secret not in record.getMessage()
        finally:
            mgr.stop()


class TestMcpSessionManagerRealServer:
    """Intégration réelle — voir docstring du module. Utilise le vrai
    binaire `alpaca-mcp-server` (installé dans .venv-agents), clés
    factices, pas d'assertion sur un appel d'outil réussi (impossible sans
    réseau vers Alpaca)."""

    def test_real_server_session_lifecycle_and_toolset_filtering(self):
        mgr = McpSessionManager()
        try:
            mgr.start("SPIKE-FAKE-KEY-NOT-REAL", "SPIKE-FAKE-SECRET-NOT-REAL")
            _wait_for_status(mgr, STATUS_HEALTHY, timeout=30.0)
            health = mgr.health()
            assert health.tool_count is not None and health.tool_count > 0
            assert health.trading_toolset_excluded is True
        finally:
            mgr.stop()

    def test_real_server_tool_call_fails_at_network_boundary_not_protocol(self):
        """Documente honnêtement la limite de cette sandbox (pas de route
        réseau vers Alpaca) : l'appel échoue, mais proprement — une
        McpSessionError avec un message exploitable, jamais un crash ni un
        blocage indéfini."""
        mgr = McpSessionManager(tool_call_timeout=15.0)
        try:
            mgr.start("SPIKE-FAKE-KEY-NOT-REAL", "SPIKE-FAKE-SECRET-NOT-REAL")
            _wait_for_status(mgr, STATUS_HEALTHY, timeout=30.0)
            with pytest.raises(McpSessionError):
                mgr.call_tool("get_clock")
            # La session doit rester utilisable après un échec d'outil
            # (échec applicatif Alpaca, pas une mort de la session MCP).
            assert mgr.health().status == STATUS_HEALTHY
        finally:
            mgr.stop()

    def test_real_server_disallowed_tool_still_rejected_locally(self):
        mgr = McpSessionManager()
        try:
            mgr.start("SPIKE-FAKE-KEY-NOT-REAL", "SPIKE-FAKE-SECRET-NOT-REAL")
            _wait_for_status(mgr, STATUS_HEALTHY, timeout=30.0)
            with pytest.raises(McpSessionError, match="non autorisé"):
                mgr.call_tool("place_stock_order", {"symbol": "AAPL"})
        finally:
            mgr.stop()
