"""Interrupteur IA global — §B10 "Interrupteur IA dédié dans Settings"
(décision D026, risque R15 : coût token IA incontrôlé sur une instance
publique déployée).

Persisté dans Redis (clé simple, pas de table dédiée — cohérent avec
l'échelle V1, même principe que les heartbeats de `eventbus.py`) plutôt
que seulement dans une variable d'environnement statique : Zac doit
pouvoir couper tous les appels IA en un clic, sans redéployer. La valeur
par défaut (tant que personne n'a jamais touché à l'interrupteur) vient de
la configuration de chaque service (`Settings.ai_calls_enabled` côté
backend, variable d'environnement côté agents).

Utilisé à la fois par `backend` (endpoint de lecture/écriture, pas encore
d'écran Settings dédié — voir AVANCEMENT.md, le contrat existe avant
l'écran, même principe que B04/B06/B07) et par `agents` (chaque agent
consommateur d'IA doit vérifier ce flag avant tout appel `AIProvider`,
et pas seulement au démarrage — l'interrupteur doit agir immédiatement)."""

from __future__ import annotations

AI_ENABLED_REDIS_KEY = "settings:ai_calls_enabled"


def get_ai_calls_enabled(redis_client, *, default: bool) -> bool:
    raw = redis_client.get(AI_ENABLED_REDIS_KEY)
    if raw is None:
        return default
    if isinstance(raw, bytes):
        raw = raw.decode()
    return raw == "true"


def set_ai_calls_enabled(redis_client, enabled: bool) -> None:
    redis_client.set(AI_ENABLED_REDIS_KEY, "true" if enabled else "false")
