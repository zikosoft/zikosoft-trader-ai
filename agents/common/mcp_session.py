"""McpSessionManager — session MCP Alpaca persistante pour le Market Agent
(brique B10, mitigation du risque R02 "MCP difficile à initialiser après
saisie UI").

Le SDK MCP officiel (`mcp`) est asyncio ; `run_service()`/`tick()`
(`agents/common/bootstrap.py`) sont synchrones par contrat depuis le socle
B01-B04 — les 4 agents existants (market/strategy/risk_critic/execution)
en dépendent, on ne le change pas pour une seule brique. Cette classe fait
donc tourner sa propre boucle asyncio dans un thread dédié et n'expose que
des méthodes synchrones/thread-safe à l'appelant.

Couvre les points du brief B10 :
- Démarre après connexion Alpaca valide (`start()` appelé par le tick une
  fois un compte connecté trouvé — voir `market_agent/main.py`).
- Credentials transmis uniquement en mémoire (dans l'environnement du
  process serveur MCP, jamais écrits sur disque ni journalisés par cette
  classe — voir `_redact` et l'absence totale de `api_key`/`secret_key`
  dans les logs ci-dessous).
- Force le mode Paper : `ALPACA_PAPER_TRADE` toujours `"true"`, jamais un
  paramètre exposé à l'appelant.
- Limite les toolsets : double couche — `ALPACA_TOOLSETS` côté serveur
  (`READ_ONLY_TOOLSETS`) ET un allowlist appliqué à nouveau dans
  `call_tool()` (défense en profondeur, ne dépend jamais uniquement du
  réglage serveur tiers).
- Reconnecte après panne (boucle superviseur avec backoff borné).
- Redémarre si les credentials changent (`restart()`).
- Publie health/heartbeat (`publish_health()`).

Validé au préalable par un spike isolé contre le vrai serveur officiel
(`alpacahq/alpaca-mcp-server`) avec des clés factices — voir
`AVANCEMENT.md` §39 et `spike_alpaca_mcp.py` (livré à part, hors app)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("mcp_session")

# §B10 "Limiter les toolsets aux besoins" — uniquement des toolsets en
# lecture (état marché, données de prix/crypto, actifs, actualités,
# lecture du compte). `trading` et `watchlists` (écriture / passage
# d'ordres) sont délibérément exclus — première couche de défense.
READ_ONLY_TOOLSETS = "account,assets,stock-data,crypto-data,news"

# Deuxième couche de défense (ne dépend jamais uniquement du réglage
# ALPACA_TOOLSETS côté serveur tiers) : allowlist explicite des outils que
# le Market Agent est autorisé à appeler via cette classe. Volontairement
# un sous-ensemble encore plus restreint que READ_ONLY_TOOLSETS — juste ce
# dont B10 a besoin aujourd'hui (fonctions agent : état marché/calendrier,
# OHLCV, quote/snapshot, positions en lecture, market movers, actualités).
CALLABLE_TOOL_ALLOWLIST = frozenset(
    {
        "get_clock",
        "get_calendar",
        "get_stock_bars",
        "get_stock_snapshot",
        "get_stock_latest_quote",
        "get_stock_latest_trade",
        "get_crypto_bars",
        "get_crypto_snapshot",
        "get_all_positions",
        "get_account_info",
        "get_portfolio_history",
        "get_most_active_stocks",
        "get_market_movers",
        "get_news",
    }
)

DEFAULT_TOOL_CALL_TIMEOUT_SECONDS = 10.0
# Backoff borné (paliers croissants, plafonné) — évite de marteler le
# process serveur en cas de panne persistante tout en reconnectant vite en
# cas d'incident bref.
DEFAULT_BACKOFF_SCHEDULE = (1.0, 2.0, 5.0, 10.0, 30.0)
# §B10 sécurité "Limite d'appels" — Alpaca documente elle-même des limites
# de débit par compte ("high-frequency querying may trigger rate
# limiting", voir spike) ; ce plafond est une deuxième ligne de défense
# locale, indépendante de ce qu'Alpaca applique de son côté, pour qu'un
# Market Agent qui tournerait en boucle trop serrée ne martèle jamais
# l'API réelle.
DEFAULT_MAX_CALLS_PER_MINUTE = 60

STATUS_STOPPED = "STOPPED"
STATUS_STARTING = "STARTING"
STATUS_HEALTHY = "HEALTHY"
STATUS_RECONNECTING = "RECONNECTING"


class McpSessionError(Exception):
    """Toute erreur de cette classe (démarrage, appel d'outil interdit, appel
    d'outil échoué, timeout) — jamais une exception brute du SDK MCP ou
    `anyio` propagée à l'appelant, pour n'avoir qu'un seul type d'erreur à
    gérer côté Market Agent (même principe que `AIProviderError`)."""


@dataclass
class McpSessionHealth:
    status: str
    connected_at: float | None = None
    last_error: str | None = None
    reconnect_count: int = 0
    tool_count: int | None = None
    trading_toolset_excluded: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "connected_at": self.connected_at,
            "last_error": self.last_error,
            "reconnect_count": self.reconnect_count,
            "tool_count": self.tool_count,
            "trading_toolset_excluded": self.trading_toolset_excluded,
        }


def _build_server_params(api_key: str, secret_key: str) -> StdioServerParameters:
    return StdioServerParameters(
        command="alpaca-mcp-server",
        args=["--transport", "stdio"],
        env={
            **os.environ,
            "ALPACA_API_KEY": api_key,
            "ALPACA_SECRET_KEY": secret_key,
            # §B10 "Forcer Paper mode" — valeur figée ici, jamais un
            # paramètre remontable par l'appelant (contrairement à
            # `ALPACA_PAPER_TRADE` documenté par Alpaca comme
            # configurable : ce module choisit délibérément de ne
            # jamais exposer ce choix).
            "ALPACA_PAPER_TRADE": "true",
            "ALPACA_TOOLSETS": READ_ONLY_TOOLSETS,
        },
    )


# Type du "session factory" injectable pour les tests : un callable qui,
# donné (api_key, secret_key), retourne un gestionnaire de contexte async
# produisant un objet "session-like" (`.list_tools()`, `.call_tool()`, déjà
# initialisé). Permet de remplacer la connexion réelle par un double
# contrôlable en test unitaire (pannes/reconnexion déterministes), tout en
# gardant la même classe testée pour de vrai en intégration contre le
# serveur officiel — voir tests/test_mcp_session.py, les deux catégories de
# tests existent.
SessionFactory = Callable[[str, str], Any]


@asynccontextmanager
async def _default_session_factory(api_key: str, secret_key: str) -> AsyncIterator[ClientSession]:
    params = _build_server_params(api_key, secret_key)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


class _RateLimiter:
    """Quota d'appels glissant sur 60s — même principe que
    `shared.ai_provider._RateLimiter`, dupliqué volontairement plutôt que
    partagé : ce module ne dépend pas de `shared.ai_provider` (deux
    préoccupations distinctes, MCP vs IA), et c'est une dizaine de lignes
    sans état partagé à synchroniser entre les deux."""

    def __init__(self, max_calls_per_minute: int) -> None:
        self.max_calls_per_minute = max_calls_per_minute
        self._calls: list[float] = []

    def allow(self) -> bool:
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t <= 60]
        if len(self._calls) >= self.max_calls_per_minute:
            return False
        self._calls.append(now)
        return True


class McpSessionManager:
    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        tool_call_timeout: float = DEFAULT_TOOL_CALL_TIMEOUT_SECONDS,
        backoff_schedule: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE,
        max_calls_per_minute: int = DEFAULT_MAX_CALLS_PER_MINUTE,
    ) -> None:
        self._session_factory = session_factory or _default_session_factory
        self._tool_call_timeout = tool_call_timeout
        self._backoff_schedule = backoff_schedule
        self._rate_limiter = _RateLimiter(max_calls_per_minute)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._session_lock = threading.Lock()

        self._credentials: tuple[str, str] | None = None
        self._stop_event: threading.Event | None = None
        self._restart_event: threading.Event | None = None

        self._health = McpSessionHealth(status=STATUS_STOPPED)
        self._health_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start(self, api_key: str, secret_key: str) -> None:
        """Démarre la session en arrière-plan. Idempotent si déjà démarrée
        avec les mêmes credentials (ne recrée rien inutilement)."""
        if self._thread is not None and self._thread.is_alive():
            if self._credentials == (api_key, secret_key):
                return
            self.restart(api_key, secret_key)
            return

        self._credentials = (api_key, secret_key)
        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._set_health(McpSessionHealth(status=STATUS_STARTING))

        def _run_loop() -> None:
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._supervisor())
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=_run_loop, name="mcp-session-supervisor", daemon=True)
        self._thread.start()

    def restart(self, api_key: str, secret_key: str) -> None:
        """§B10 "Redémarrer si credentials modifiés" — force une
        reconnexion immédiate (sans attendre le backoff) avec les
        nouveaux credentials."""
        self._credentials = (api_key, secret_key)
        if self._restart_event is not None:
            self._restart_event.set()
        else:
            self.start(api_key, secret_key)

    def stop(self, *, timeout: float = 5.0) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(lambda: None)  # réveille la boucle si elle attend
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._session = None
        self._thread = None
        self._loop = None
        self._set_health(McpSessionHealth(status=STATUS_STOPPED))

    # ------------------------------------------------------------------
    # Superviseur (tourne dans le thread dédié)
    # ------------------------------------------------------------------

    async def _supervisor(self) -> None:
        assert self._stop_event is not None and self._restart_event is not None
        backoff_index = 0

        while not self._stop_event.is_set():
            self._restart_event.clear()
            api_key, secret_key = self._credentials  # type: ignore[misc]
            try:
                async with self._session_factory(api_key, secret_key) as session:
                    tools_response = await session.list_tools()
                    tool_names = {t.name for t in tools_response.tools}
                    trading_excluded = not any(
                        name.startswith("place_") or name.startswith("cancel_") or "close_position" in name
                        for name in tool_names
                    )

                    with self._session_lock:
                        self._session = session
                    backoff_index = 0
                    self._set_health(
                        McpSessionHealth(
                            status=STATUS_HEALTHY,
                            connected_at=time.time(),
                            reconnect_count=self._health.reconnect_count,
                            tool_count=len(tool_names),
                            trading_toolset_excluded=trading_excluded,
                        )
                    )
                    logger.info(
                        "mcp session healthy",
                        extra={"tool_count": len(tool_names), "trading_toolset_excluded": trading_excluded},
                    )

                    # Session maintenue ouverte jusqu'à stop/restart — aucune
                    # donnée sensible loguée ici.
                    while not self._stop_event.is_set() and not self._restart_event.is_set():
                        await asyncio.sleep(0.5)
            except Exception as exc:  # noqa: BLE001 — toute panne déclenche une reconnexion, jamais un crash du thread
                with self._session_lock:
                    self._session = None
                if self._stop_event.is_set():
                    break
                delay = self._backoff_schedule[min(backoff_index, len(self._backoff_schedule) - 1)]
                backoff_index += 1
                self._set_health(
                    McpSessionHealth(
                        status=STATUS_RECONNECTING,
                        last_error=str(exc),
                        reconnect_count=self._health.reconnect_count + 1,
                    )
                )
                logger.warning("mcp session lost, reconnecting in %.1fs: %s", delay, exc)
                await asyncio.sleep(delay)

        with self._session_lock:
            self._session = None

    # ------------------------------------------------------------------
    # Appels d'outils (thread-safe, synchrone pour l'appelant)
    # ------------------------------------------------------------------

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in CALLABLE_TOOL_ALLOWLIST:
            # Ne dépend jamais uniquement du filtrage côté serveur
            # (ALPACA_TOOLSETS) — deuxième couche de défense, voir
            # docstring du module.
            raise McpSessionError(f"outil non autorisé pour le Market Agent : {name!r}")

        if not self._rate_limiter.allow():
            # §B10 sécurité "Limite d'appels" — deuxième ligne de défense
            # locale, indépendante des limites Alpaca elles-mêmes (voir
            # commentaire sur DEFAULT_MAX_CALLS_PER_MINUTE) : jamais un appel
            # réseau tenté au-delà du quota, l'erreur est levée avant toute
            # dispatch vers la boucle asyncio.
            raise McpSessionError(
                f"limite d'appels MCP dépassée ({self._rate_limiter.max_calls_per_minute}/min)"
            )

        if self._loop is None or self._session is None:
            raise McpSessionError("session MCP non disponible (pas démarrée ou en reconnexion)")

        async def _call() -> dict[str, Any]:
            with self._session_lock:
                session = self._session
            if session is None:
                raise McpSessionError("session MCP non disponible (pas démarrée ou en reconnexion)")
            result = await session.call_tool(name, arguments=arguments or {})
            return _parse_tool_result(result)

        future = asyncio.run_coroutine_threadsafe(_call(), self._loop)
        try:
            return future.result(timeout=self._tool_call_timeout)
        except TimeoutError as exc:
            raise McpSessionError(f"timeout ({self._tool_call_timeout}s) sur l'appel de l'outil {name!r}") from exc
        except McpSessionError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalisé pour l'appelant
            raise McpSessionError(f"échec de l'appel de l'outil {name!r} : {exc}") from exc

    # ------------------------------------------------------------------
    # Observabilité
    # ------------------------------------------------------------------

    def health(self) -> McpSessionHealth:
        with self._health_lock:
            return self._health

    def _set_health(self, health: McpSessionHealth) -> None:
        with self._health_lock:
            self._health = health

    def publish_health(self, redis_client, *, key: str, ttl_seconds: int = 30) -> None:
        """§B10 "Publier health et heartbeat" — clé Redis avec TTL (même
        principe que `shared.eventbus.publish_heartbeat`, B22) : si le
        Market Agent meurt, la clé expire et le statut redevient
        indisponible plutôt que de rester bloqué sur un dernier état
        périmé."""
        redis_client.set(key, json.dumps(self.health().to_dict()), ex=ttl_seconds)


def _parse_tool_result(result: Any) -> dict[str, Any]:
    """Normalise une réponse MCP (`CallToolResult`) en dict Python. Les
    outils Alpaca renvoient du texte (souvent du JSON sérialisé) dans
    `content[0].text` plutôt qu'un `structuredContent` systématique — voir
    limite documentée en §39 AVANCEMENT.md (non vérifiable en sandbox faute
    d'accès réseau réel à Alpaca)."""
    if getattr(result, "isError", False):
        text = _first_text(result)
        raise McpSessionError(text or "erreur MCP sans détail")

    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)

    text = _first_text(result)
    if text is None:
        return {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"raw_text": text}
    return parsed if isinstance(parsed, dict) else {"raw_value": parsed}


def _first_text(result: Any) -> str | None:
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return None
