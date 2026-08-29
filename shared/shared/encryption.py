"""Primitives de chiffrement des secrets (B08, relocalisé en B10 depuis
`backend/app/encryption.py` pour être réutilisable par `agents` —
McpSessionManager, B10, doit déchiffrer les clés Alpaca stockées par B07
pour ouvrir une session MCP, et `agents` n'a pas accès au package `backend`
(image Docker séparée, voir agents/Dockerfile)).

Ce module ne connaît PAS la config d'un service en particulier (pas
d'import de `backend.app.config` ni d'`os.environ` ici) — la clé est
toujours un paramètre explicite. Chaque service (`backend`, `agents`) garde
son propre petit wrapper qui lit sa source de configuration et appelle ces
primitives — voir `backend/app/encryption.py` et
`agents/common/encryption.py`, mêmes signatures `encrypt_secret(plaintext)`
/ `decrypt_secret(ciphertext)` que celles déjà livrées à Zac (patch
v0.3.0) : ce refactor ne casse aucun appelant existant.

Fernet (bibliothèque `cryptography`) : AES-128-CBC + HMAC-SHA256, chiffrement
authentifié — toute altération du ciphertext est détectée au déchiffrement
(`InvalidToken`), pas seulement un déchiffrement silencieusement corrompu.

`CURRENT_KEY_VERSION` est écrit dans `UserTradingAccount.encryption_key_version`
à chaque chiffrement — prépare une future rotation de clé sans avoir à la
construire maintenant."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

CURRENT_KEY_VERSION = 1


class EncryptionKeyMissing(RuntimeError):
    """La clé de chiffrement n'est pas configurée (absente ou invalide).
    Volontairement une erreur explicite plutôt qu'un secret stocké en clair
    en silence (§B08 checklist "Tester clé de chiffrement absente")."""


class SecretDecryptionFailed(ValueError):
    """Le ciphertext ne se déchiffre pas avec la clé fournie — mauvaise clé
    (rotation non gérée), donnée corrompue, ou falsifiée."""


def _fernet(key: str) -> Fernet:
    if not key:
        raise EncryptionKeyMissing(
            "clé de chiffrement absente ou vide — impossible de chiffrer/"
            "déchiffrer un secret. Voir .env.example pour générer une clé Fernet valide."
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionKeyMissing(
            "clé de chiffrement invalide (attendu : 32 octets base64 urlsafe "
            "avec padding) — voir .env.example."
        ) from exc


def encrypt_secret(plaintext: str, *, key: str) -> str:
    """Chiffre `plaintext` avec `key`. Ne jamais appeler avec une chaîne
    vide côté appelant sans le vouloir explicitement — un secret vide n'a
    pas de sens métier (voir validation dans schemas/onboarding.py)."""
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str, *, key: str) -> str:
    try:
        return _fernet(key).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise SecretDecryptionFailed(
            "secret illisible : mauvaise clé de chiffrement ou donnée corrompue"
        ) from exc
