"""Routes d'authentification locale (B05)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.error_log import ErrorModule, log_error
from shared.errors import ErrorCode

from ..api_errors import api_error_response
from ..auth import create_session, get_current_user, revoke_session
from ..config import settings
from ..db import engine, get_db
from ..models import User
from ..rate_limit import is_rate_limited, register_attempt
from ..redis_client import redis_client
from ..schemas.auth import DemoCredentialsResponse, LoginRequest, MeResponse, UserOut
from ..security import verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Message volontairement identique pour "email inconnu" et "mot de passe
# incorrect" — ne jamais révéler si un email existe (§B05 "message d'erreur
# sans fuite d'information").
_INVALID_CREDENTIALS_MESSAGE = "Email ou mot de passe incorrect."


def _client_ip(request: Request) -> str:
    # Pas de X-Forwarded-For en V1 (pas de reverse proxy en dev) — à revoir
    # au déploiement (B38) si le VPS est derrière un proxy/load balancer.
    return request.client.host if request.client else "unknown"


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    ip = _client_ip(request)

    if is_rate_limited(redis_client, ip):
        return api_error_response(
            429,
            ErrorCode.RATE_LIMITED,
            "Trop de tentatives de connexion. Réessayez dans une minute.",
        )

    register_attempt(redis_client, ip)

    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        log_error(
            engine,
            module=ErrorModule.AUTH,
            feature="login",
            severity="WARNING",
            response_or_error="invalid credentials",
            http_status=401,
            error_code=ErrorCode.UNAUTHORIZED.value,
        )
        return api_error_response(401, ErrorCode.UNAUTHORIZED, _INVALID_CREDENTIALS_MESSAGE)

    token, _session = create_session(db, user)
    db.commit()

    response = JSONResponse(content=MeResponse(user=UserOut.model_validate(user)).model_dump(mode="json"))
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        # `secure=True` exigerait HTTPS même en dev local (http://localhost) ;
        # activé uniquement quand l'app tourne dans un environnement autre
        # que "local" (voir B38 — déploiement derrière un sous-domaine HTTPS).
        secure=settings.app_env != "local",
        path="/",
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        revoke_session(db, token)
        db.commit()
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key=settings.session_cookie_name, path="/")
    return response


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user=UserOut.model_validate(user))


@router.get("/demo-credentials", response_model=DemoCredentialsResponse | None)
def demo_credentials() -> DemoCredentialsResponse | None:
    """Pratique pour un jury de hackathon (préremplissage du formulaire de
    login) — désactivable via `DEMO_CREDENTIALS_VISIBLE=false` (voir
    `.env.example`, pertinent si l'environnement déployé doit être durci)."""
    if not settings.demo_credentials_visible:
        return None
    return DemoCredentialsResponse(email=settings.demo_user_email, password=settings.demo_user_password)
