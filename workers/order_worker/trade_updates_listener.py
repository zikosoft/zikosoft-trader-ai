"""TradeUpdatesListener — B17, connexion WebSocket persistante au flux
`trade_updates` d'Alpaca (checklist "Consommer updates Alpaca"/"Gérer
partial fill"/"WebSocket coupé puis restauré").

Même architecture que `McpSessionManager` (B10, `agents/common/
mcp_session.py`) et pour la même raison : `run_service()`/`tick()`
(`agents/common/bootstrap.py`) sont synchrones par contrat, cette classe
fait donc tourner sa propre boucle asyncio dans un thread dédié et
n'expose que des méthodes synchrones à l'appelant (`start`/`stop`/
`health`). Contrairement à `McpSessionManager`, le protocole ici est le
WebSocket JSON simple d'Alpaca (pas MCP) — pas de dépendance au SDK `mcp`,
utilise directement `websockets`.

Découplage volontaire : cette classe ne touche JAMAIS la base de données
elle-même — elle appelle `on_event(event)` pour chaque événement
`trade_updates` reçu, et `on_reconnected()` après une reconnexion réussie
(jamais après la toute première connexion) pour que l'appelant déclenche sa
propre réconciliation REST (voir `workers/order_worker/main.py`). Même
principe de séparation que `McpSessionManager`, qui ne touche pas non plus
Postgres/Redis directement.

**Honnêteté sur la couverture de test** : comme le spike MCP de B10, cette
classe n'a jamais pu être validée contre le vrai WebSocket Alpaca (aucun
accès réseau sortant ni clé réelle dans cet environnement) — testée ici
contre un double injectable (`connection_factory`), même principe que
`SessionFactory`/`_ScriptedFactory` dans `test_mcp_session.py`. Le
protocole (URL, message d'authentification, message d'abonnement, forme
des événements) est documenté d'après la documentation officielle Alpaca
(voir AVANCEMENT.md, journal B17)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger("trade_updates_listener")

DEFAULT_BACKOFF_SCHEDULE = (1.0, 2.0, 5.0, 10.0, 30.0)

STATUS_STOPPED = "STOPPED"
STATUS_STARTING = "STARTING"
STATUS_HEALTHY = "HEALTHY"
STATUS_RECONNECTING = "RECONNECTING"

# Événements `trade_updates` qui modifient l'état d'un ordre localement —
# voir `workers/order_worker/order_lifecycle.py::apply_trade_update`. Liste
# fermée volontairement : un type d'événement inconnu est journalisé et
# ignoré plutôt que de faire planter le worker (§B04 "un message en échec
# ne doit jamais arrêter le tick", même principe appliqué ici).
KNOWN_EVENT_TYPES = frozenset(
    {
        "new",
        "accepted",
        "pending_new",
        "fill",
        "partial_fill",
        "canceled",
        "pending_cancel",
        "rejected",
        "replaced",
        "pending_replace",
        "order_replace_rejected",
        "order_cancel_rejected",
        "expired",
        "done_for_day",
        "stopped",
        "calculated",
        "suspended",
    }
)


def _default_trade_updates_url() -> str:
    # §B07 "Mode Paper verrouillé" — même verrouillage qu'`AlpacaClient`/
    # `AlpacaTradingClient`, aucune option pour cibler l'URL live.
    return os.environ.get("ALPACA_PAPER_STREAM_URL", "wss://paper-api.alpaca.markets/stream")


class WebSocketConnectionLike(Protocol):
    """Contrat minimal attendu d'une connexion — `websockets.connect()`
    (production) et les doubles de test le respectent tous deux."""

    async def send(self, message: str) -> None: ...

    async def recv(self) -> str: ...


ConnectionFactory = Callable[[str], Any]


@asynccontextmanager
async def _default_connection_factory(url: str):
    import websockets  # import différé — évite la dépendance en environnement de test pur

    async with websockets.connect(url) as ws:
        yield ws


@dataclass
class ListenerHealth:
    status: str
    connected_at: float | None = None
    last_error: str | None = None
    reconnect_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "connected_at": self.connected_at,
            "last_error": self.last_error,
            "reconnect_count": self.reconnect_count,
        }


class TradeUpdatesListenerError(Exception):
    """Erreur de protocole (échec d'authentification notamment) — jamais
    une exception brute du SDK `websockets` propagée à l'appelant."""


def parse_trade_update(raw: str) -> dict | None:
    """Pure, testable indépendamment de toute connexion réelle. Retourne
    `None` (jamais une exception) pour tout message qui n'est pas un
    événement `trade_updates` exploitable — un message d'authentification,
    un ping, ou un message malformé ne doit jamais faire planter la boucle
    de réception (même discipline anti-crash que le reste du pipeline)."""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or parsed.get("stream") != "trade_updates":
        return None
    data = parsed.get("data")
    if not isinstance(data, dict) or "event" not in data or "order" not in data:
        return None
    if data["event"] not in KNOWN_EVENT_TYPES:
        logger.warning("type d'événement trade_updates inconnu, ignoré : %r", data["event"])
        return None
    return data


def _is_auth_success(raw: str) -> bool:
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return False
    data = parsed.get("data") if isinstance(parsed, dict) else None
    return isinstance(data, dict) and data.get("status") == "authorized"


class TradeUpdatesListener:
    def __init__(
        self,
        *,
        on_event: Callable[[dict], None],
        on_reconnected: Callable[[], None] | None = None,
        connection_factory: ConnectionFactory | None = None,
        backoff_schedule: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE,
        url: str | None = None,
    ) -> None:
        self._on_event = on_event
        self._on_reconnected = on_reconnected
        self._connection_factory = connection_factory or _default_connection_factory
        self._backoff_schedule = backoff_schedule
        self._url = url or _default_trade_updates_url()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._credentials: tuple[str, str] | None = None

        self._health = ListenerHealth(status=STATUS_STOPPED)
        self._health_lock = threading.Lock()

    def health(self) -> ListenerHealth:
        with self._health_lock:
            return ListenerHealth(**vars(self._health))

    def _set_health(self, **updates: Any) -> None:
        with self._health_lock:
            for k, v in updates.items():
                setattr(self._health, k, v)

    # ------------------------------------------------------------------
    # Cycle de vie — même schéma que McpSessionManager.start/stop.
    # ------------------------------------------------------------------
    def start(self, api_key: str, secret_key: str) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._credentials = (api_key, secret_key)
        self._stop_event = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._set_health(status=STATUS_STARTING)

        def _run_loop() -> None:
            assert self._loop is not None
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._supervisor())
            finally:
                self._loop.close()

        self._thread = threading.Thread(target=_run_loop, name="trade-updates-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        self._set_health(status=STATUS_STOPPED)

    # ------------------------------------------------------------------
    async def _supervisor(self) -> None:
        assert self._credentials is not None
        api_key, secret_key = self._credentials
        attempt = 0
        first_connect = True

        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                async with self._connection_factory(self._url) as conn:
                    await conn.send(json.dumps({"action": "auth", "key": api_key, "secret": secret_key}))
                    auth_raw = await conn.recv()
                    if not _is_auth_success(auth_raw):
                        raise TradeUpdatesListenerError("authentification WebSocket Alpaca refusée")

                    await conn.send(json.dumps({"action": "listen", "data": {"streams": ["trade_updates"]}}))

                    self._set_health(status=STATUS_HEALTHY, last_error=None)
                    attempt = 0
                    if not first_connect and self._on_reconnected is not None:
                        # §checklist B17 "Réconcilier par REST après
                        # reconnexion" — déclenché ICI, jamais à la toute
                        # première connexion (rien à réconcilier alors).
                        try:
                            self._on_reconnected()
                        except Exception:  # noqa: BLE001 — une réconciliation en échec ne doit pas tuer la connexion
                            logger.exception("échec de la réconciliation après reconnexion")
                    first_connect = False

                    while self._stop_event is not None and not self._stop_event.is_set():
                        raw = await conn.recv()
                        event = parse_trade_update(raw)
                        if event is None:
                            continue
                        try:
                            self._on_event(event)
                        except Exception:  # noqa: BLE001 — un événement en échec ne doit jamais tuer la connexion
                            logger.exception("échec du traitement d'un événement trade_updates")
            except Exception as exc:  # noqa: BLE001 — reconnexion à backoff, jamais un crash du thread
                if self._stop_event is not None and self._stop_event.is_set():
                    break
                logger.warning("connexion trade_updates perdue, reconnexion programmée : %s", exc)
                self._set_health(status=STATUS_RECONNECTING, last_error=str(exc))
                self._health.reconnect_count += 1
                delay = self._backoff_schedule[min(attempt, len(self._backoff_schedule) - 1)]
                attempt += 1
                await asyncio.sleep(delay)
