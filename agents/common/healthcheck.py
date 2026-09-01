"""Healthcheck Docker pour les agents/workers (image partagée, D003).

Contrairement à `backend-api` (endpoint HTTP `/health`), les agents/workers
n'exposent pas de port — leur seul signal de vie est le heartbeat Redis à
TTL publié par `run_service()` (voir `agents/common/bootstrap.py`, B22).
Ce script sert de `HEALTHCHECK` Docker : il échoue (exit 1) si la clé
`heartbeat:<SERVICE_NAME>` est absente ou expirée, ce qui arrive dès que le
service ne boucle plus (crash, deadlock, perte de connexion Redis prolongée).

**Distinction volontaire (B22) : `DEGRADED` reste un succès Docker (exit 0).**
Ce script vérifie que le CONTENEUR est vivant et boucle (liveness), pas que
sa logique métier réussit (readiness métier, exposée séparément par
`GET /api/system/health`, agrégée par `workers/watchdog/`) — un `tick()` qui
échoue en boucle ne doit pas faire redémarrer le conteneur par Docker
(`restart: unless-stopped` + healthcheck qui échoue = boucle de redémarrage
inutile), c'est au Watchdog de le signaler comme incident, pas à Docker de
tenter une réparation par redémarrage qui ne réglera rien si la cause est,
par exemple, une dépendance externe indisponible. `STOPPED` (arrêt propre)
et l'absence de heartbeat (jamais vu, ou expiré) restent un échec (exit 1) —
mais dans le cas `STOPPED`, le process est de toute façon en train de
sortir, ce script n'aura généralement pas l'occasion d'observer cet état.

`SERVICE_NAME` doit correspondre exactement au nom passé à `run_service()`
dans le `main.py` du service (voir docker-compose.yml, variable
d'environnement par service).
"""

from __future__ import annotations

import os
import sys

from common.bootstrap import build_redis_client
from shared.eventbus import read_heartbeat

# §B22 — voir docstring du module : DEGRADED est un service vivant qui boucle
# mais dont la dernière tentative de `tick()` a échoué, pas un conteneur mort.
_CONTAINER_ALIVE_STATES = ("HEALTHY", "DEGRADED")


def main() -> int:
    service_name = os.environ.get("SERVICE_NAME")
    if not service_name:
        print("healthcheck: SERVICE_NAME env var missing", file=sys.stderr)
        return 1
    try:
        client = build_redis_client()
        value = read_heartbeat(client, service_name)
    except Exception as exc:  # noqa: BLE001 — toute erreur = pas sain
        print(f"healthcheck: could not reach redis: {exc}", file=sys.stderr)
        return 1
    if value is None or value.get("state") not in _CONTAINER_ALIVE_STATES:
        print(f"healthcheck: no fresh heartbeat for {service_name}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
