# Image commune agents + workers (décision D003 — "un container par agent,
# une image commune pour les agents", évite de dupliquer les builds). Le rôle
# exact (market-agent, risk-engine, ...) est déterminé par la commande passée
# dans docker-compose.yml, pas par l'image elle-même.

FROM python:3.11-slim AS base

WORKDIR /srv

COPY shared /srv/shared
COPY agents/requirements.txt /srv/agents/requirements.txt
# WORKDIR posé sur /srv/agents AVANT ce RUN : requirements.txt contient
# `-e ../shared`, un chemin relatif résolu par pip par rapport au répertoire
# courant du process — pas à l'emplacement du fichier requirements.txt. Même
# bug (et même correctif) que backend/Dockerfile, voir son commentaire pour
# le détail et AVANCEMENT.md pour la reproduction avant correctif.
WORKDIR /srv/agents
RUN pip install --no-cache-dir -e /srv/shared \
    && pip install --no-cache-dir -r requirements.txt

COPY agents /srv/agents
COPY workers /srv/workers
# strategies/ (B11 — Strategy Registry) : le futur Strategy Agent (B13, pas
# encore construit) devra évaluer les modules de stratégie directement
# (`strategies.<type_code>.engine.evaluate`), pas seulement lire leurs
# définitions via l'API backend — copié dès maintenant pour ne pas ajouter
# un deuxième correctif Docker plus tard (même précaution que le bug
# `-e ../shared` déjà rencontré).
COPY strategies /srv/strategies

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv/agents:/srv/workers:/srv

# WORKDIR déjà /srv/agents depuis plus haut (posé avant le RUN pip install,
# voir commentaire ci-dessus) — pas besoin de le reposer ici.

# Pas de CMD par défaut : chaque service du compose fournit sa propre
# commande (ex. `python market_agent/main.py`, `python ../workers/risk_engine/main.py`).
