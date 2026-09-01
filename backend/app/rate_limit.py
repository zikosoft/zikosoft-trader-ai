"""Rate limiting du login (B05, checklist "Rate limiting du login").

Fenêtre fixe simple (INCR + EX) par adresse IP, appuyée sur Redis — cohérent
avec l'infra déjà présente (B04) plutôt que d'ajouter une dépendance dédiée.
Volontairement basique pour un socle de hackathon : pas de fenêtre glissante,
pas de blocage par email (un attaquant distribué sur plusieurs IP n'est pas
freiné) — durcissement possible en B32 si le besoin se confirme.
"""

from __future__ import annotations

import redis

from .config import settings


def _key(ip: str) -> str:
    return f"login_attempts:{ip}"


def is_rate_limited(client: redis.Redis, ip: str) -> bool:
    """True si `ip` a déjà atteint le nombre maximal de tentatives dans la
    fenêtre en cours. Ne consomme pas de tentative (lecture seule) — utiliser
    `register_attempt` pour compter un essai."""
    current = client.get(_key(ip))
    return current is not None and int(current) >= settings.login_rate_limit_max_attempts


def register_attempt(client: redis.Redis, ip: str) -> int:
    """Incrémente le compteur de tentatives pour `ip` (fenêtre glissante
    ré-armée à chaque premier essai de la fenêtre) et retourne le nouveau
    total. Appelé sur CHAQUE tentative de login (succès ou échec) — même un
    login réussi compte, pour éviter qu'un attaquant alterne des logins
    valides/invalides sans jamais déclencher la limite."""
    key = _key(ip)
    pipe = client.pipeline()
    pipe.incr(key)
    pipe.expire(key, settings.login_rate_limit_window_seconds, nx=True)
    count, _ = pipe.execute()
    return int(count)
