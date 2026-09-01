"""B30 — grille de limites par profil d'expérience (novice/intermediate/
expert). Table statique, volontairement pas en base : ce sont des
constantes produit (§checklist B30), pas des données que l'utilisateur
édite — même philosophie que `strategy_instances.MAX_SAVED_STRATEGIES` et
consorts (B12), simplement rendues profil-dépendantes ici.

**Unification avec B09** : le plafond "10 symboles surveillés cumulés"
annoncé par B09 (§checklist "Maximum 10 symboles monitorés cumulés") EST
`PROFILE_LIMITS["expert"]["max_symbols"]` ci-dessous — un seul mécanisme
(`strategy_instances._enforce_symbol_limit`, désormais profil-aware),
jamais deux limites potentiellement contradictoires. B09 décrit donc
honnêtement le plafond haut de cette grille, pas une limite indépendante.

**Portée volontairement limitée à "stocker + afficher" pour les champs de
risque (§B30 D0xx) :** `order_risk_pct`/`daily_loss_pct`/`approval_mode`
sont exposés par `GET /api/settings/profile` pour que l'écran Settings les
affiche honnêtement, mais RIEN ne les fait encore appliquer par le Risk
Engine (B15) — celui-ci ne sait tourner qu'avec des limites de risque
réellement configurées, qu'il ne sait pas encore lire depuis un profil
utilisateur (limitation déjà documentée, voir R17). Câbler cette
application reste un travail futur, pas fabriqué ici.

Seuls `max_active_strategies`/`max_symbols` sont RÉELLEMENT appliqués
aujourd'hui (`strategy_instances.py`, `_active_limit_for`/`_symbol_limit_for`).

`workers/risk_engine/main.py` duplique volontairement `MAX_ACTIVE_STRATEGIES`/
`MAX_CUMULATIVE_SYMBOLS` en dur à leurs valeurs "expert" (3/10) comme
garde-fou de dernier recours (défense en profondeur, image Docker séparée,
pas d'accès à `User`/ORM) — laissé délibérément NON profil-aware : la
vraie porte d'entrée utilisateur (`strategy_instances.py`) applique déjà la
bonne limite par profil ; ce filet de sécurité reste à la borne haute,
valide pour tous les profils, plutôt que de dupliquer une logique de
lookup profil dans un module qui n'a structurellement pas accès à `User`."""

from __future__ import annotations

from typing import TypedDict


class ProfileLimits(TypedDict):
    max_active_strategies: int
    max_symbols: int
    order_risk_pct: float
    daily_loss_pct: float
    approval_mode: str  # "mandatory" | "optional" | "configurable"


PROFILE_NOVICE = "novice"
PROFILE_INTERMEDIATE = "intermediate"
PROFILE_EXPERT = "expert"

# Ordre croissant d'autonomie — utilisé pour détecter une augmentation de
# niveau (§checklist "Avertissement si le niveau d'autonomie augmente").
PROFILE_ORDER: tuple[str, ...] = (PROFILE_NOVICE, PROFILE_INTERMEDIATE, PROFILE_EXPERT)

DEFAULT_PROFILE = PROFILE_NOVICE

PROFILE_LIMITS: dict[str, ProfileLimits] = {
    PROFILE_NOVICE: {
        "max_active_strategies": 1,
        "max_symbols": 2,
        "order_risk_pct": 0.5,
        "daily_loss_pct": 1.0,
        "approval_mode": "mandatory",
    },
    PROFILE_INTERMEDIATE: {
        "max_active_strategies": 2,
        "max_symbols": 5,
        "order_risk_pct": 1.0,
        "daily_loss_pct": 2.0,
        "approval_mode": "optional",
    },
    PROFILE_EXPERT: {
        "max_active_strategies": 3,
        "max_symbols": 10,
        "order_risk_pct": 2.0,
        "daily_loss_pct": 4.0,
        "approval_mode": "configurable",
    },
}


def limits_for(profile: str) -> ProfileLimits:
    """Repli honnête sur le profil le plus prudent (`novice`) pour toute
    valeur inattendue plutôt que de lever — la colonne `users.experience_profile`
    est déjà contrainte en base (`CHECK`, migration 0005), ce repli ne sert
    qu'à ne jamais planter une lecture si cette contrainte venait à
    manquer (ex. donnée insérée hors ORM)."""
    return PROFILE_LIMITS.get(profile, PROFILE_LIMITS[DEFAULT_PROFILE])


def is_increase(*, from_profile: str, to_profile: str) -> bool:
    try:
        return PROFILE_ORDER.index(to_profile) > PROFILE_ORDER.index(from_profile)
    except ValueError:
        return False
