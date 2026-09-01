# Conventions du dépôt

Ce document couvre les conventions minimales du socle (B01). Il ne remplace
pas la documentation publique finale (B34).

## Nommage

- Répertoires et fichiers Python : `snake_case`.
- Répertoires et fichiers TypeScript/React : `PascalCase` pour les
  composants (`App.tsx`), `camelCase` pour le reste.
- Services Docker Compose : `kebab-case`, identique au nom du répertoire
  quand c'est un service applicatif dédié (`market-agent` → `agents/market_agent/`).
- Streams Redis et tables PostgreSQL : voir `shared/shared/events.py`
  (`Streams`) et `backend/app/models/` — ne pas introduire de nouveau nom
  sans l'ajouter au contrat commun.

## Runtimes

- Python : voir `.python-version` (3.11), aligné sur les images Docker
  (`python:3.11-slim`).
- Node.js : voir `.nvmrc` (20), aligné sur `frontend/Dockerfile`
  (`node:20-slim`).

## Branches et pull requests

- `main` reste toujours déployable (au sens : les tests et `ruff check`
  passent, `docker compose config` est valide).
- Une branche par brique ou groupe de briques cohérent : `brick/B0X-slug`.
- Une PR décrit la ou les briques couvertes et référence leur ID
  (`AVANCEMENT.md`) ; elle n'est mergée que si la brique correspondante
  respecte la définition de « terminé » (§1.3 de `AVANCEMENT.md`).

## Qualité

- Python : `ruff check .` (lint) — voir `pyproject.toml`.
- TypeScript : `npm run lint` dans `frontend/` — voir `frontend/eslint.config.js`.
- Tests : `pytest` (voir `Makefile` → `make test`).
