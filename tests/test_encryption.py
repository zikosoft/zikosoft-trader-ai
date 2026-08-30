"""B08 — chiffrement des secrets."""

from __future__ import annotations

import pytest
from app import encryption
from app.config import settings


def test_encrypt_decrypt_round_trip():
    ciphertext = encryption.encrypt_secret("my-alpaca-api-key")
    assert ciphertext != "my-alpaca-api-key"
    assert encryption.decrypt_secret(ciphertext) == "my-alpaca-api-key"


def test_ciphertext_is_not_the_plaintext_and_changes_each_time():
    """Fernet inclut un nonce/timestamp : deux chiffrements du même texte
    produisent des ciphertexts différents (non déterministe, empêche de
    repérer des doublons par simple comparaison du ciphertext)."""
    c1 = encryption.encrypt_secret("same-secret")
    c2 = encryption.encrypt_secret("same-secret")
    assert c1 != c2
    assert encryption.decrypt_secret(c1) == "same-secret"
    assert encryption.decrypt_secret(c2) == "same-secret"


def test_missing_key_raises_explicit_error(monkeypatch):
    monkeypatch.setattr(settings, "app_encryption_key", "")
    with pytest.raises(encryption.EncryptionKeyMissing):
        encryption.encrypt_secret("x")
    with pytest.raises(encryption.EncryptionKeyMissing):
        encryption.decrypt_secret("whatever")


def test_invalid_key_format_raises_explicit_error(monkeypatch):
    monkeypatch.setattr(settings, "app_encryption_key", "not-a-valid-fernet-key")
    with pytest.raises(encryption.EncryptionKeyMissing):
        encryption.encrypt_secret("x")


def test_tampered_ciphertext_is_rejected():
    ciphertext = encryption.encrypt_secret("secret-value")
    tampered = ciphertext[:-4] + ("A" if ciphertext[-4] != "A" else "B") + ciphertext[-3:]
    with pytest.raises(encryption.SecretDecryptionFailed):
        encryption.decrypt_secret(tampered)


def test_current_key_version_is_a_positive_int():
    assert isinstance(encryption.CURRENT_KEY_VERSION, int)
    assert encryption.CURRENT_KEY_VERSION >= 1
