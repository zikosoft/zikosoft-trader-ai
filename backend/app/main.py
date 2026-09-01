"""Point d'entrée FastAPI — backend-api (B01-B04/B36 socle + B05 auth).

Le socle (santé technique, santé du schéma, format d'erreur commun) reste
minimal par design. B05 ajoute l'authentification locale (`/api/auth/*`) —
le reste de la surface API (§18 de la spec) arrive dans les briques
suivantes (B07+).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from shared.errors import APIError, ErrorCode
from shared.eventbus import publish_heartbeat
from shared.logging import configure_json_logging
from shared.risk_governance import get_trading_kill_switch_engaged
from shared.watchdog import DEGRADED, DISCONNECTED, ESSENTIAL_SERVICES, HEALTHY, STARTING

from .config import settings
from .db import SessionLocal, engine
from .redis_client import redis_client
from .routers.agent_activity import agents_router, risk_router
from .routers.agent_room import router as agent_room_router
from .routers.ai_settings import router as ai_settings_router
from .routers.alerts import router as alerts_router
from .routers.assets import router as assets_router
from .routers.auth import router as auth_router
from .routers.context import router as context_router
from .routers.kill_switch import router as kill_switch_router
from .routers.market import router as market_router
from .routers.onboarding import router as onboarding_router
from .routers.orders import router as orders_router
from .routers.portfolio import router as portfolio_router
from .routers.replay import router as replay_router
from .routers.strategies import router as strategies_router
from .routers.strategy_instances import router as strategy_instances_router
from .routers.user_profile import router as user_profile_router
from .seed import run_seed
from .strategy_sync import sync_from_directory

logger = configure_json_logging("backend-api")

_HEARTBEAT_SERVICE_NAME = "backend-api"


async def _backend_heartbeat_loop(stop_event: asyncio.Event) -> None:
    """§B22 — `backend-api` ne passe pas par `common.bootstrap.run_service`
    (c'est un serveur HTTP, pas une boucle de tick comme les agents/workers)
    mais doit publier le même heartbeat Redis pour être agrégé par le
    Watchdog au même titre que les 8 autres services essentiels. État publié
    = readiness métier (PostgreSQL + Redis réellement joignables), pas
    seulement "le process asyncio tourne" — même discipline que
    `agents/common/bootstrap.py::run_once`."""
    redis_client = redis.Redis.from_url(settings.redis_url)
    ttl = settings.heartbeat_ttl_seconds
    interval = settings.heartbeat_interval_seconds
    try:
        while not stop_event.is_set():
            state = "HEALTHY"
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                redis_client.ping()
            except Exception:  # noqa: BLE001 — une panne de dépendance ne doit jamais tuer ce process
                state = "DEGRADED"
            try:
                publish_heartbeat(redis_client, _HEARTBEAT_SERVICE_NAME, state=state, ttl_seconds=ttl)
            except Exception:  # noqa: BLE001 — Redis injoignable ne doit pas non plus tuer ce process
                logger.exception("backend-api: échec de publication du heartbeat")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
    finally:
        # §B22 — même discipline que `run_service` : distingue un arrêt
        # propre (redéploiement, `docker compose down`) d'une vraie panne.
        with contextlib.suppress(Exception):  # noqa: BLE001 — on sort de toute façon
            publish_heartbeat(redis_client, _HEARTBEAT_SERVICE_NAME, state="STOPPED", ttl_seconds=ttl)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """B05 ("créer l'utilisateur démo au premier démarrage") : le seed est
    idempotent (voir tests/test_db_models.py et le journal AVANCEMENT.md
    B03), donc sans risque à rejouer à chaque démarrage du conteneur — pas
    seulement au tout premier. Une erreur ici est loguée mais ne doit pas
    empêcher l'API de démarrer (santé/diagnostic doivent rester consultables
    même si le seed échoue, ex. Postgres pas encore tout à fait prêt malgré
    le healthcheck)."""
    try:
        run_seed()
    except Exception:  # noqa: BLE001 — voir docstring
        logger.exception("startup seed failed — the demo user may not exist yet")

    # §B11 "chargement automatique des modules" — scanne `strategies/` et
    # synchronise la table `strategy_definitions` à chaque démarrage
    # (idempotent, voir strategy_sync.py) : un module invalide ou une
    # panne DB transitoire ne doit jamais empêcher l'API de démarrer, même
    # principe que le seed ci-dessus.
    try:
        db = SessionLocal()
        try:
            sync_from_directory(db)
        finally:
            db.close()
    except Exception:  # noqa: BLE001 — voir commentaire ci-dessus
        logger.exception("startup strategy registry sync failed — definitions may be stale")

    # §B22 — heartbeat périodique de `backend-api` lui-même (voir docstring
    # de `_backend_heartbeat_loop`), démarré en tâche de fond une fois le
    # reste du démarrage terminé.
    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(_backend_heartbeat_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await heartbeat_task


app = FastAPI(title="ZikosoftTrader AI — backend-api", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(context_router)
app.include_router(onboarding_router)
app.include_router(ai_settings_router)
app.include_router(strategies_router)
app.include_router(strategy_instances_router)
app.include_router(portfolio_router)
app.include_router(replay_router)
app.include_router(orders_router)
app.include_router(agents_router)
app.include_router(risk_router)
app.include_router(market_router)
app.include_router(agent_room_router)
app.include_router(kill_switch_router)
app.include_router(assets_router)
app.include_router(alerts_router)
app.include_router(user_profile_router)

# Statuts HTTP -> code d'erreur applicatif (shared.errors.ErrorCode), pour
# que TOUTE HTTPException levée n'importe où dans l'API (pas seulement B05)
# ressorte dans le format commun `{"error": {...}}` plutôt que le
# `{"detail": ...}` par défaut de FastAPI/Starlette.
_STATUS_TO_ERROR_CODE = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    429: ErrorCode.RATE_LIMITED,
    502: ErrorCode.UPSTREAM_ERROR,
    504: ErrorCode.UPSTREAM_TIMEOUT,
}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = _STATUS_TO_ERROR_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    details = exc.detail if isinstance(exc.detail, dict) else None
    error = APIError(code=code, message=message, details=details)
    return JSONResponse(status_code=exc.status_code, content=error.to_response())


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled exception on %s: %s", request.url.path, exc, exc_info=exc)
    error = APIError(code=ErrorCode.INTERNAL_ERROR, message="Internal server error")
    return JSONResponse(status_code=500, content=error.to_response())


@app.get("/health")
def health() -> dict:
    """Liveness simple — le process répond. Ne vérifie pas les dépendances
    (voir /api/system/health, B22, pour la readiness métier complète)."""
    return {"status": "ok", "service": "backend-api"}


_LATEST_SERVICE_HEALTH_SQL = text(
    """
    SELECT DISTINCT ON (service_name) service_name, state, last_heartbeat_at
    FROM service_health_events
    WHERE service_name = ANY(:service_names)
    ORDER BY service_name, created_at DESC
    """
)

# §B31 — dernier événement d'audit kill switch ENGAGED (utilisé uniquement
# quand le flag lu depuis Redis est `true`, pour donner à la bannière
# globale de quoi/qui/pourquoi sans poller une deuxième route dédiée).
_LATEST_KILL_SWITCH_ENGAGE_SQL = text(
    """
    SELECT user_id, detail, created_at
    FROM audit_events
    WHERE action = 'KILL_SWITCH_ENGAGED'
    ORDER BY created_at DESC
    LIMIT 1
    """
)


@app.get("/api/system/health")
def system_health() -> dict:
    """Readiness agrégée des 9 services essentiels (§checklist B22) :
    PostgreSQL et Redis sont vérifiés en direct ici (latence connue, pas de
    dépendance à la fraîcheur du Watchdog pour ces deux-là — ce sont les
    dépendances du process `backend-api` lui-même). Les 7 autres
    (`backend-api` inclus, dont le heartbeat est publié par
    `_backend_heartbeat_loop` ci-dessus) sont lus depuis `service_health_events`
    (dernier état connu, écrit par `workers/watchdog/` — B22), jamais
    interrogés en direct depuis ici (ce serait dupliquer la logique
    d'agrégation du Watchdog, D... même discipline que D028 : un seul point
    d'écriture par préoccupation). Un service jamais observé par le Watchdog
    (table vide pour ce nom) est honnêtement rapporté `STARTING`, jamais
    fabriqué comme `HEALTHY`."""
    checks: dict[str, dict] = {}
    overall_ok = True

    started = time.monotonic()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = {"status": HEALTHY, "latency_ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        overall_ok = False
        checks["postgres"] = {"status": DISCONNECTED, "error": str(exc)}

    started = time.monotonic()
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        checks["redis"] = {"status": HEALTHY, "latency_ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        overall_ok = False
        checks["redis"] = {"status": DISCONNECTED, "error": str(exc)}

    watchdog_tracked = [s for s in ESSENTIAL_SERVICES if s not in ("postgres", "redis")]
    latest_by_service: dict[str, dict] = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(_LATEST_SERVICE_HEALTH_SQL, {"service_names": watchdog_tracked}).mappings().all()
        latest_by_service = {row["service_name"]: row for row in rows}
    except Exception:  # noqa: BLE001 — déjà couvert par le check postgres ci-dessus s'il a échoué
        pass

    for service_name in watchdog_tracked:
        row = latest_by_service.get(service_name)
        if row is None:
            overall_ok = False
            checks[service_name] = {"status": STARTING}
            continue
        checks[service_name] = {
            "status": row["state"],
            "last_heartbeat_at": row["last_heartbeat_at"].isoformat() if row["last_heartbeat_at"] else None,
        }
        if row["state"] != HEALTHY:
            overall_ok = False

    # §B26 "Kill switch" — le dashboard affiche l'état RÉEL du kill switch
    # trading (déjà appliqué par le Risk Engine depuis B15, voir
    # `shared/shared/risk_governance.py`), en lecture seule : aucun bouton
    # d'activation ici, ce widget n'est qu'un indicateur honnête. Le
    # bouton/l'action complète (confirmation renforcée, annulation des
    # ordres ouverts, audit event, alertes) reste le périmètre de B31 —
    # exposer juste le flag ne peut pas raisonnablement attendre B31 (même
    # raisonnement que le docstring de `risk_governance.py` pour le test P0
    # de B15). Volontairement PAS dans `checks` : ce n'est pas un incident
    # (D056), c'est un état de sécurité intentionnel distinct.
    # `None` si Redis est injoignable (déjà rapporté par `checks["redis"]`
    # ci-dessus) : jamais fabriquer `False` ("trading actif") quand l'état
    # réel n'a justement pas pu être lu.
    try:
        kill_switch_engaged = get_trading_kill_switch_engaged(redis_client, default=False)
    except Exception:  # noqa: BLE001
        kill_switch_engaged = None

    # §B31 "Alerte in-app" — le détail (qui/quand/pourquoi) voyage dans la
    # MÊME réponse publique déjà pollée par `IncidentBanner`-style
    # composants, plutôt qu'une route dédiée supplémentaire (même principe
    # que le flag lui-même, ajouté ici en B26/D068). `None` tant que le
    # flag n'est pas `true` — pas de détail à afficher, jamais un ancien
    # événement DISENGAGE présenté à tort comme "raison de l'arrêt actuel".
    kill_switch_detail = None
    if kill_switch_engaged:
        try:
            with engine.connect() as conn:
                row = conn.execute(_LATEST_KILL_SWITCH_ENGAGE_SQL).mappings().first()
            if row is not None:
                kill_switch_detail = {
                    "actor_user_id": str(row["user_id"]) if row["user_id"] else None,
                    "reason": (row["detail"] or {}).get("reason"),
                    "occurred_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
        except Exception:  # noqa: BLE001 — déjà couvert par le check postgres ci-dessus s'il a échoué
            pass

    return {
        "status": HEALTHY if overall_ok else DEGRADED,
        "checks": checks,
        "trading_kill_switch_engaged": kill_switch_engaged,
        "trading_kill_switch_detail": kill_switch_detail,
    }


logging.getLogger("backend-api").info("backend-api started (env=%s)", settings.app_env)
