"""Route de l'interrupteur IA global — §B10 "Interrupteur IA dédié dans
Settings" (D026, R15). Le contrat existe avant l'écran dédié (pas encore
construit, arrivera avec un futur écran Settings) — même principe que les
contrats publiés en avance ailleurs dans le projet (B04, B06, B07)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..config import settings
from ..models import User
from ..redis_client import redis_client
from ..schemas.ai_settings import AISettingsOut, UpdateAISettingsRequest

router = APIRouter(prefix="/api/settings/ai", tags=["settings"])


def _current() -> AISettingsOut:
    from shared.ai_governance import get_ai_calls_enabled

    return AISettingsOut(
        enabled=get_ai_calls_enabled(redis_client, default=settings.ai_calls_enabled),
        max_calls_per_minute=settings.ai_max_calls_per_minute,
        high_stakes_model=settings.ai_model_high_stakes,
        low_stakes_model=settings.ai_model_low_stakes,
    )


@router.get("", response_model=AISettingsOut)
def get_ai_settings(user: User = Depends(get_current_user)) -> AISettingsOut:
    return _current()


@router.put("", response_model=AISettingsOut)
def update_ai_settings(
    payload: UpdateAISettingsRequest, user: User = Depends(get_current_user)
) -> AISettingsOut:
    from shared.ai_governance import set_ai_calls_enabled

    # §D026 "en un clic sans redéployer" : effet immédiat — le prochain
    # tick de n'importe quel agent consommateur d'IA relit ce flag avant
    # son prochain appel (voir agents/market_agent/main.py).
    set_ai_calls_enabled(redis_client, payload.enabled)
    return _current()
