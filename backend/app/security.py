"""Primitives de sécurité (B05) : hachage de mot de passe et jetons de
session opaques. Regroupé ici pour que `seed.py` (création du mot de passe
démo) et `auth.py` (vérification au login) partagent la même implémentation
— pas de duplication de logique de sécurité entre deux fichiers."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

_PBKDF2_ITERATIONS = 260_000

# Longueur du jeton de session en octets bruts avant encodage urlsafe
# (32 octets = 256 bits d'entropie, largement suffisant).
_SESSION_TOKEN_BYTES = 32


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    """PBKDF2-HMAC-SHA256. Format stocké `pbkdf2_sha256$iterations$salt$hash`
    — permet de faire évoluer l'algorithme (ex. argon2) sans casser les mots
    de passe existants (on peut détecter l'ancien préfixe et re-hacher au
    prochain login réussi si besoin, non implémenté en V1)."""
    salt = salt or os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = encoded.split("$")
        assert algo == "pbkdf2_sha256"
        salt = bytes.fromhex(salt_hex)
        expected = hash_password(password, salt=salt)
        return hmac.compare_digest(expected, encoded)
    except Exception:  # noqa: BLE001 — un format invalide = mot de passe refusé, pas une exception
        return False


def generate_session_token() -> str:
    """Jeton opaque envoyé au navigateur (cookie). Jamais stocké en clair
    côté serveur — voir `hash_session_token`."""
    return secrets.token_urlsafe(_SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """SHA-256 simple (pas PBKDF2) : contrairement à un mot de passe, un
    jeton de session a déjà 256 bits d'entropie aléatoire — un hachage lent
    n'apporte rien contre le brute-force et coûterait cher sur *chaque*
    requête authentifiée (le hash est recalculé à chaque appel de
    `get_current_user`)."""
    return hashlib.sha256(token.encode()).hexdigest()
