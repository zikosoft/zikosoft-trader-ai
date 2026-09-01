"""Cœur de l'authentification locale (B05) : création/validation de session,
dépendance FastAPI `get_current_user` pour protéger une route.

Le mécanisme est prêt à être appliqué à toute route métier — mais le socle
actuel (B01-B04, B36 partiel) n'expose encore aucune route métier, seulement
`/health` (public, par design) et les routes `/api/auth/*` elles-mêmes. La
protection réelle "aucune route métier sans session" (critère d'acceptation
B05) devient vérifiable dès que B07+ ajoutent des endpoints métier — il
suffira d'ajouter `user: User = Depends(get_current_user)` à leur signature.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User, UserSession
from .security import generate_session_token, hash_session_token

# Message générique volontairement identique pour "session absente",
# "session expirée" et "session révoquée" — ne pas donner d'indice sur la
# raison exacte (§B05 "message d'erreur sans fuite d'information").
_INVALID_SESSION_DETAIL = "Session invalide ou expirée."


def create_session(db: Session, user: User) -> tuple[str, UserSession]:
    """Crée une nouvelle session pour `user` et retourne le jeton en clair
    (à poser dans le cookie de réponse — jamais renvoyé ni stocké ensuite)
    ainsi que la ligne `UserSession` créée."""
    token = generate_session_token()
    now = datetime.now(UTC)
    session = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.flush()
    return token, session


def revoke_session(db: Session, token: str) -> None:
    """Idempotent : ne fait rien si le jeton ne correspond à aucune session
    active (déjà révoquée, expirée, ou jamais existé) — un logout répété ne
    doit jamais lever d'erreur côté client."""
    token_hash = hash_session_token(token)
    session = db.execute(
        select(UserSession).where(
            UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None)
        )
    ).scalar_one_or_none()
    if session is not None:
        session.revoked_at = datetime.now(UTC)
        db.flush()


def _resolve_session(db: Session, token: str | None) -> tuple[User, UserSession] | None:
    if not token:
        return None
    token_hash = hash_session_token(token)
    session = db.execute(
        select(UserSession).where(UserSession.token_hash == token_hash)
    ).scalar_one_or_none()
    if session is None:
        return None
    if session.revoked_at is not None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    session.last_seen_at = datetime.now(UTC)
    db.flush()
    return user, session


def get_current_user(
    session_token: str | None = Cookie(default=None, alias=settings.session_cookie_name),
    db: Session = Depends(get_db),
) -> User:
    """Dépendance FastAPI à utiliser sur toute future route métier :
    `user: User = Depends(get_current_user)`."""
    resolved = _resolve_session(db, session_token)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_SESSION_DETAIL)
    user, _ = resolved
    return user
