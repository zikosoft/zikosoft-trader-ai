"""Engine et session SQLAlchemy partagés par l'API et (via import) les scripts
de migration / seed."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """Une transaction par requête : commit automatique si la route se
    termine sans exception, rollback sinon — le pattern standard FastAPI/
    SQLAlchemy.

    Sans ça, une route qui modifie des données via cette dépendance sans
    appeler `db.commit()` elle-même perd silencieusement ses écritures (le
    `rollback` implicite de `Session.close()` sur une transaction encore
    ouverte s'en charge). C'est exactement le bug trouvé pendant le
    développement de B05 : `get_current_user` met à jour `last_seen_at` sur
    la session active, mais aucune route ne rappelait explicitement
    `db.commit()` après — la mise à jour n'était donc jamais persistée.
    `db.commit()` explicite dans une route reste sans danger (idempotent
    avec ce pattern), donc les routes existantes (`login`/`logout`) n'ont pas
    besoin d'être changées."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
