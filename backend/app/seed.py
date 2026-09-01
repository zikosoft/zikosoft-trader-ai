"""Seed technique idempotent (B03/B05) — exécuté au démarrage du conteneur
`backend-api` (voir docker-compose.yml, commande `python -m app.seed`).

Crée, s'ils n'existent pas déjà :
- l'utilisateur démo (email/mot de passe depuis .env, mot de passe haché) ;
- le provider Alpaca (§9.2 — seedé, non éditable depuis l'UI) ;
- les trois execution_contexts PAPER / REPLAY / DRY_RUN.

Aucun ordre Paper fictif n'est jamais seedé (§9.3/D009 — transparence,
empty states plutôt que fausses performances).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import ExecutionContext, TradingProvider, User
from .security import (  # noqa: F401 — verify_password ré-exporté (B05, tests)
    hash_password,
    verify_password,
)

logger = logging.getLogger("seed")


def seed_demo_user(db: Session) -> User:
    user = db.query(User).filter_by(email=settings.demo_user_email).one_or_none()
    if user:
        return user
    user = User(
        email=settings.demo_user_email,
        password_hash=hash_password(settings.demo_user_password),
        display_name="Demo User",
    )
    db.add(user)
    db.flush()
    logger.info("seeded demo user %s", user.email)
    return user


def seed_trading_provider(db: Session) -> TradingProvider:
    provider = db.query(TradingProvider).filter_by(code="alpaca").one_or_none()
    if provider:
        return provider
    provider = TradingProvider(code="alpaca", label="Alpaca", is_active=True)
    db.add(provider)
    db.flush()
    logger.info("seeded trading provider alpaca")
    return provider


def seed_execution_contexts(db: Session, user: User) -> None:
    """Crée les 3 emplacements de contexte (PAPER/REPLAY/DRY_RUN) mais aucun
    n'est actif au seed (B06 : « Choose your experience » après login décide
    du premier contexte actif — au plus un actif à la fois, contrainte posée
    en base, voir migration 0003)."""
    for kind, label in (
        ("PAPER", "Alpaca Paper"),
        ("REPLAY", "Historical Replay"),
        ("DRY_RUN", "Dry Run (interne, tests/QA — B33)"),
    ):
        existing = (
            db.query(ExecutionContext).filter_by(kind=kind, user_id=user.id).one_or_none()
        )
        if existing:
            continue
        db.add(ExecutionContext(kind=kind, label=label, user_id=user.id, is_active=False))
        logger.info("seeded execution_context %s", kind)


def run_seed() -> None:
    db = SessionLocal()
    try:
        user = seed_demo_user(db)
        seed_trading_provider(db)
        seed_execution_contexts(db, user)
        db.commit()
        logger.info("seed complete")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    from shared.logging import configure_json_logging

    configure_json_logging("seed")
    run_seed()
