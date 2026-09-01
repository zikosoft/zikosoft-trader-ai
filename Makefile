.PHONY: up up-core down build migrate test test-agents seed logs config

# Socle complet (core + observabilité) — équivaut à `docker compose up`,
# le socle n'a plus de profil (voir docker-compose.yml)
up:
	docker compose --profile observability up -d --build

# Socle applicatif seul (DB, cache, API, frontend, agents, workers) — pas de
# profil à passer, c'est le comportement par défaut de `docker compose up`
up-core:
	docker compose up -d --build

down:
	docker compose --profile observability down

build:
	docker compose --profile observability build

# Migrations Alembic (exécutées localement contre le Postgres du compose ;
# à conteneuriser si besoin en CI plus tard)
migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && python -m app.seed

# Suite backend (auth, contextes, onboarding, chiffrement, ...) — nécessite
# le venv backend (voir CONTRIBUTING.md / backend/requirements*.txt).
test:
	pytest

# Suite agents/workers (B10 — McpSessionManager, AIProvider ; B14 — Risk
# Critic ; B15 — Risk Engine ; B16 — Execution & Explanation Agent ; B17 —
# Order Worker/AlpacaTradingClient/TradeUpdatesListener — tous sans
# dépendance FastAPI/backend) — nécessite un venv SÉPARÉ (agents/
# requirements.txt embarque un starlette/fastmcp qui entre en conflit avec
# le fastapi pinné par backend/requirements.txt si installés dans le même
# environnement — voir la note dans agents/requirements.txt).
# Créer ce venv une fois :
#   python3 -m venv .venv-agents && .venv-agents/bin/pip install -r agents/requirements.txt
# NB : test_strategy_agent.py (B13) reste exclu de cette cible car il
# importe `app.main` (FastAPI/backend) — il tourne sous le venv backend
# (cible `test`) comme le reste de la suite.
# §B17 — complété rétroactivement : cette cible n'avait plus été mise à
# jour depuis B14 (test_risk_engine.py et test_execution_explanation_agent.py,
# livrés en B15/B16, en étaient absents) ; corrigé en même temps que l'ajout
# des trois nouveaux fichiers de B17.
# §B18 — test_alpaca_portfolio_client.py ajouté ici par cohérence avec
# test_alpaca_trading_client.py (B17, même situation : aucune dépendance
# agents-only en réalité, seulement httpx, mais regroupé avec le reste de sa
# brique). test_portfolio_worker.py, lui, reste dans la cible `test` (venv
# backend) — comme test_risk_engine.py, il n'a besoin ni de `mcp` ni de
# Redis (voir son docstring).
test-agents:
	.venv-agents/bin/pytest tests/test_mcp_session.py tests/test_ai_provider.py tests/test_market_agent.py tests/test_risk_critic_agent.py tests/test_risk_engine.py tests/test_execution_explanation_agent.py tests/test_order_worker.py tests/test_alpaca_trading_client.py tests/test_trade_updates_listener.py tests/test_alpaca_portfolio_client.py -v

logs:
	docker compose --profile observability logs -f

# Valide docker-compose.yml sans nécessiter de daemon Docker actif
config:
	docker compose --profile observability config
