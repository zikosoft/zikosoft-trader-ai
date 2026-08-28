FROM python:3.11-slim AS base

WORKDIR /srv

# Dépendances système minimales pour psycopg (binaire) — pas de compilateur requis.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Le package `shared` est copié et installé avant le code applicatif pour
# profiter du cache Docker (il change moins souvent que backend/app).
COPY shared /srv/shared
COPY backend/requirements.txt /srv/backend/requirements.txt
# WORKDIR posé sur /srv/backend AVANT ce RUN (pas après) : requirements.txt
# contient `-e ../shared`, un chemin relatif que pip résout par rapport au
# répertoire courant du process, PAS par rapport à l'emplacement du fichier
# requirements.txt lui-même. Avec WORKDIR=/srv (comme dans une version
# précédente de ce Dockerfile), `../shared` pointait vers `/shared`, qui
# n'existe pas — seul `/srv/shared` existe — d'où l'échec
# "../shared is not a valid editable requirement" au build. Reproduit et
# vérifié en dehors de Docker avant ce correctif (voir AVANCEMENT.md).
WORKDIR /srv/backend
RUN pip install --no-cache-dir -e /srv/shared \
    && pip install --no-cache-dir -r requirements.txt

COPY backend /srv/backend
# strategies/ (Strategy Registry) : dossier des modules de stratégie
# développeur, scanné au démarrage par `backend/app/strategy_sync.py`
# (`DEFAULT_STRATEGIES_DIR` résout vers ce dossier via un chemin relatif au
# fichier, donc il doit rester au même niveau que `backend/`/`shared/` ici).
COPY strategies /srv/strategies
# replay_data/ (B19 Étape A — Replay Engine) : peut être vide dans l'image —
# `shared/shared/replay_market_data.py::DEFAULT_REPLAY_DATASET_PATH` 
# `scripts/fetch_replay_dataset.py` avec ses propres clés Alpaca, `GET
# /api/replay/dataset` répond honnêtement 404 plutôt que de fabriquer des
# données (voir routers/replay.py).
COPY replay_data /srv/replay_data

ENV PYTHONUNBUFFERED=1 \
    # /srv/backend : imports applicatifs habituels (`app.*`). /srv : permet
    # aux modules de stratégie (B11/B12) de s'importer entre eux par chemin
    # absolu (`strategies.base.indicators`) en plus des imports relatifs
    # internes déjà supportés directement par le loader dynamique.
    PYTHONPATH=/srv/backend:/srv

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
