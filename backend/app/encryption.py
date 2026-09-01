"""Chiffrement des secrets côté backend (B08) — clés Alpaca aujourd'hui
(B07), tout futur secret de fournisseur (IA, Telegram) plus tard, même
mécanisme.

Wrapper mince autour de `shared.encryption` (relocalisé là en B10 pour être
réutilisable par `agents` — voir docstring de ce module partagé). Signatures
inchangées (`encrypt_secret(plaintext)`, `decrypt_secret(ciphertext)`) :
aucun appelant existant (onboarding.py, tests) n'a besoin d'être modifié."""

from __future__ import annotations

from shared.encryption import (
    CURRENT_KEY_VERSION,
    EncryptionKeyMissing,
    SecretDecryptionFailed,
)
from shared.encryption import decrypt_secret as _decrypt_secret
from shared.encryption import encrypt_secret as _encrypt_secret

from .config import settings

__all__ = [
    "CURRENT_KEY_VERSION",
    "EncryptionKeyMissing",
    "SecretDecryptionFailed",
    "encrypt_secret",
    "decrypt_secret",
]


def encrypt_secret(plaintext: str) -> str:
    return _encrypt_secret(plaintext, key=settings.app_encryption_key)


def decrypt_secret(ciphertext: str) -> str:
    return _decrypt_secret(ciphertext, key=settings.app_encryption_key)
