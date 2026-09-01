"""Bootstrap commun aux agents et workers (image partagée, décision D003).

Ce module ne contient volontairement AUCUNE logique métier — c'est le socle
(B01-B04) : connexion Redis/PostgreSQL, heartbeat périodique (B22), logging
JSON, boucle de service avec arrêt propre sur SIGTERM. Chaque service
(market_agent, strategy_agent, risk_engine, ...) importe ce module et fournit
sa propre fonction `tick()` — la logique métier de chaque service arrive
brique par brique (B10, B13, B14, B15, B16, B17, B20, B22).

**Heartbeat = readiness métier depuis B22, pas seulement "le process boucle"
(§11.1) :** avant B22, le heartbeat était publié INCONDITIONNELLEMENT avant
chaque appel à `tick()` — un service dont `tick()` échouait en boucle restait
donc vu "HEALTHY" par quiconque le lit, alors que sa logique métier ne
fonctionnait plus. Depuis B22, le heartbeat est publié APRÈS la tentative de
`tick()`, avec l'état réellement observé (`HEALTHY` si `tick()` a réussi,
`DEGRADED` s'il a levé une exception) — le service reste vivant et continue
de boucler (aucune régression sur la résilience déjà en place), mais son état
publié reflète honnêtement ce qui s'est passé. À l'arrêt propre (SIGTERM), un
dernier heartbeat `STOPPED` est publié avant de sortir de la boucle — sans
ça, un `docker compose down`/redéploiement volontaire serait indiscernable
d'une vraie panne aux yeux du watchdog (silence radio jusqu'à expiration du
TTL, lu comme `DISCONNECTED`)."""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable

import redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from shared.eventbus import publish_heartbeat
from shared.logging import configure_json_logging

_shutdown_requested = False


def _handle_sigterm(signum, frame) -> None:  # noqa: ANN001 — signature imposée par `signal`
    global _shutdown_requested
    _shutdown_requested = True


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://zikosofttrader:zikosofttrader@postgres:5432/zikosofttrader",
    )


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


def build_engine() -> Engine:
    return create_engine(_database_url(), pool_pre_ping=True, future=True)


def build_redis_client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url())


def run_once(
    service_name: str,
    tick: Callable[[Engine, redis.Redis], None],
    engine: Engine,
    redis_client: redis.Redis,
    *,
    ttl_seconds: int,
    logger,
) -> None:
    """Une itération de la boucle de service (extrait de `run_service` pour
    être testable sans boucle infinie ni `time.sleep`, B22) : tente `tick()`,
    publie le heartbeat APRÈS coup avec l'état réellement observé."""
    try:
        tick(engine, redis_client)
    except Exception:  # noqa: BLE001 — un tick en échec ne doit pas tuer le service
        logger.exception("%s tick failed", service_name)
        publish_heartbeat(redis_client, service_name, state="DEGRADED", ttl_seconds=ttl_seconds)
    else:
        publish_heartbeat(redis_client, service_name, state="HEALTHY", ttl_seconds=ttl_seconds)


def _tick_interval_override(service_name: str) -> float | None:
    """§B10 checklist "Fréquence d'analyse de la stratégie IA volontairement
    resserrée sur l'instance publique de démo, configurable par variable
    d'environnement" — trouvé absent le 28/08 (audit B10) : l'intervalle
    était figé au défaut de `run_service(..., interval_seconds=5.0)` pour
    les 9 services, aucune variable d'environnement ne pouvait le resserrer
    sans redéployer un nouveau binaire. Convention : `<SERVICE_NAME en
    MAJUSCULES, tirets -> underscores>_TICK_INTERVAL_SECONDS` (ex.
    `MARKET_AGENT_TICK_INTERVAL_SECONDS`), même style que
    `HEARTBEAT_TTL_SECONDS` déjà lu ci-dessous. Absente ou invalide -> la
    valeur passée par l'appelant (ou son défaut 5.0) reste inchangée,
    jamais de crash au démarrage pour une variable mal formée."""
    env_name = f"{service_name.upper().replace('-', '_')}_TICK_INTERVAL_SECONDS"
    raw = os.environ.get(env_name)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def run_service(
    service_name: str,
    tick: Callable[[Engine, redis.Redis], None],
    *,
    interval_seconds: float = 5.0,
) -> None:
    """Boucle de service standard : heartbeat (B22) + appel de `tick()` à
    intervalle régulier, arrêt propre sur SIGTERM (utile pour un
    `docker compose down` propre et pour les tests de panne contrôlée, B23).

    `interval_seconds` reste la valeur par défaut choisie par chaque
    service, mais peut être resserrée/desserrée sans redéploiement via
    `<SERVICE_NAME>_TICK_INTERVAL_SECONDS` (voir `_tick_interval_override`)."""
    logger = configure_json_logging(service_name)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    override = _tick_interval_override(service_name)
    if override is not None:
        interval_seconds = override

    engine = build_engine()
    redis_client = build_redis_client()
    ttl = int(os.environ.get("HEARTBEAT_TTL_SECONDS", "15"))

    # Vérifie la connectivité au démarrage plutôt que d'échouer silencieusement
    # boucle après boucle (§11.1 — la santé doit représenter la disponibilité
    # opérationnelle réelle, pas seulement "le process est démarré").
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        redis_client.ping()
        logger.info("%s started, dependencies reachable", service_name)
    except Exception as exc:  # noqa: BLE001
        logger.error("%s failed to reach dependencies at startup: %s", service_name, exc)

    while not _shutdown_requested:
        run_once(service_name, tick, engine, redis_client, ttl_seconds=ttl, logger=logger)
        time.sleep(interval_seconds)

    # §B22 — voir docstring du module : distingue un arrêt volontaire d'une
    # vraie déconnexion aux yeux du watchdog.
    publish_heartbeat(redis_client, service_name, state="STOPPED", ttl_seconds=ttl)
    logger.info("%s shutting down (SIGTERM)", service_name)
