"""Chiffrement des secrets côté agents (B10) — wrapper mince autour de
`shared.encryption`, même principe que `backend/app/encryption.py` mais lit
la clé directement depuis l'environnement (`APP_ENCRYPTION_KEY`, chargée
via `env_file: .env` dans docker-compose.yml — même fichier que backend,
voir agent-common) plutôt que depuis une classe `Settings` Pydantic : les
agents n'en ont pas, `bootstrap.py` lit déjà `DATABASE_URL`/`REDIS_URL` de
la même façon (`os.environ.get(...)`), on suit ce précédent plutôt que
d'introduire une dépendance `pydantic-settings` supplémentaire pour un seul
champ.

Utilisé par `market_agent` (McpSessionManager, B10) pour déchiffrer les
clés Alpaca stockées par B07/B08 avant d'ouvrir une session MCP."""

from __future__ import annotations

import os

from shared.encryption import CURRENT_KEY_VERSION, EncryptionKeyMissing, SecretDecryptionFailed
from shared.encryption import decrypt_secret as _decrypt_secret
from shared.encryption import encrypt_secret as _encrypt_secret

__all__ = [
    "CURRENT_KEY_VERSION",
    "EncryptionKeyMissing",
    "SecretDecryptionFailed",
    "encrypt_secret",
    "decrypt_secret",
]


def _key() -> str:
    return os.environ.get("APP_ENCRYPTION_KEY", "")


def encrypt_secret(plaintext: str) -> str:
    return _encrypt_secret(plaintext, key=_key())


def decrypt_secret(ciphertext: str) -> str:
    return _decrypt_secret(ciphertext, key=_key())
