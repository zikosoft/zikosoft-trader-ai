"""Route du profil d'expérience utilisateur (B30 — novice/intermediate/
expert). Indépendante du pipeline d'onboarding (§B07, volontairement
fragile/déjà testé, voir D081/R35) : l'onboarding lit/écrit ce profil via
CETTE route, jamais en ajoutant une étape à `_STUBBED_STEPS`/`_run_real_step`
— zéro couplage, zéro régression possible sur les étapes existantes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import profile_limits
from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..schemas.user_profile import UpdateUserProfileRequest, UserProfileOut

router = APIRouter(prefix="/api/settings/profile", tags=["settings"])


def _out(user: User) -> UserProfileOut:
    return UserProfileOut(profile=user.experience_profile, limits=profile_limits.limits_for(user.experience_profile))


@router.get("", response_model=UserProfileOut)
def get_profile(user: User = Depends(get_current_user)) -> UserProfileOut:
    return _out(user)


@router.put("", response_model=UserProfileOut)
def update_profile(
    payload: UpdateUserProfileRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserProfileOut:
    # §checklist "Avertissement si le niveau d'autonomie augmente" — le
    # backend accepte le changement tel quel (source de vérité : l'action
    # a déjà été confirmée côté frontend, `ProfileCard.tsx`, avant cet
    # appel) ; il ne recalcule/renvoie PAS lui-même un avertissement,
    # cohérent avec le reste de l'app qui ne duplique jamais côté backend
    # une confirmation déjà obtenue côté UI (même principe que le kill
    # switch, dont la phrase tapée n'est vérifiée que côté frontend).
    user.experience_profile = payload.profile
    db.commit()
    db.refresh(user)
    return _out(user)
