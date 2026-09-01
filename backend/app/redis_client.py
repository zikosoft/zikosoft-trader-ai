"""Client Redis partagé côté API (B05 — rate limiting du login). Distinct du
client construit à la volée dans `/api/system/health` (celui-ci vérifie
juste la connectivité et n'a pas besoin d'être réutilisé)."""

from __future__ import annotations

import redis

from .config import settings

redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
