"""Fixtures partagées (B33). Nécessite un PostgreSQL et un Redis accessibles
via DATABASE_URL / REDIS_URL (voir .env.example) — pas de mock pour les
tests d'intégration du socle, on veut prouver que ça marche pour de vrai."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"
WORKERS_DIR = Path(__file__).resolve().parents[1] / "workers"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(AGENTS_DIR))
sys.path.insert(0, str(WORKERS_DIR))

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://zikosofttrader:localtest@localhost:5432/zikosofttrader"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    """Le socle suppose que `alembic upgrade head` a déjà tourné (voir
    Makefile `make migrate`) ; on vérifie juste que les tables existent
    plutôt que de recréer le schéma en dehors d'Alembic."""
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    assert Base.metadata.tables, "no models registered"
    yield


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def redis_client():
    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    yield client


@pytest.fixture()
def execution_context_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture(autouse=True)
def _reset_ai_provider_cache():
    """§Correctif (audit B10) : `shared.ai_provider.get_ai_provider`
    met désormais en cache un `AIProvider` par clé API pour toute la durée
    du process (voir son docstring — c'est ce qui corrige le bug du quota
    d'appels qui ne survivait jamais à un tick). Plusieurs suites de tests
    différentes (`test_risk_critic_agent.py`, `test_execution_explanation_agent.py`)
    réutilisent la même clé API factice (`"fake-key-for-test"`) — sans ce
    reset, un test pourrait silencieusement hériter du `_RateLimiter` (ou de
    la config) laissé par un test précédent d'une AUTRE suite tournant dans
    le même process pytest (`make test-agents` les enchaîne tous). Aucun
    impact en production : ce cache n'existe que côté test, jamais appelé
    par le code applicatif réel."""
    from shared.ai_provider import reset_ai_provider_cache

    reset_ai_provider_cache()
    yield
    reset_ai_provider_cache()
