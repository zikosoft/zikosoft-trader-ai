"""Interrupteur kill switch trading — §B15 "Blocage kill switch" (test P0
requis par le brique). Aperçu volontairement minimal de la brique dédiée à
venir (B31, pas encore construite) : B15 exige un test P0 réel de blocage
kill switch, ce qui suppose UN vrai interrupteur à tester — le construire
en toute rigueur (audit trail, écran Settings, granularité par contexte...)
appartient à B31, mais le primitive lui-même (lire/écrire un flag) ne peut
pas raisonnablement attendre B31 sans laisser B15 avec un test P0 fictif.

Même schéma exact que `shared.ai_governance` (clé Redis simple, pas de
table dédiée, cohérent avec l'échelle V1) — copié délibérément plutôt que
généralisé en un helper commun : les deux interrupteurs ont des sémantiques
différentes (IA vs trading) et des consommateurs différents, un couplage
prématuré entre eux coûterait plus qu'il ne rapporterait à ce stade.

**Portée du kill switch** : quand engagé, le Risk Engine (B15) REJETTE
systématiquement toute décision de risque, quel que soit le reste des
contrôles — c'est un veto absolu, jamais contourné, jamais assoupli par un
autre contrôle. La valeur par défaut (`False`, tant que personne n'a jamais
touché l'interrupteur) signifie "trading autorisé", cohérent avec le fait
qu'aucun écran Settings ne l'expose encore (le flag Redis existe avant
l'écran, même principe que B04/B06/B07/`ai_governance.py`)."""

from __future__ import annotations

TRADING_KILL_SWITCH_REDIS_KEY = "settings:trading_kill_switch_engaged"


def get_trading_kill_switch_engaged(redis_client, *, default: bool = False) -> bool:
    raw = redis_client.get(TRADING_KILL_SWITCH_REDIS_KEY)
    if raw is None:
        return default
    if isinstance(raw, bytes):
        raw = raw.decode()
    return raw == "true"


def set_trading_kill_switch_engaged(redis_client, engaged: bool) -> None:
    redis_client.set(TRADING_KILL_SWITCH_REDIS_KEY, "true" if engaged else "false")
