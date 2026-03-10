"""Tests for libs.encryption — encrypt/decrypt roundtrip."""

import importlib
from unittest.mock import patch, MagicMock

import pytest

import libs.encryption as enc_module
from libs.encryption import encrypt_value, decrypt_value


# ── Empty / None input ──


def test_encrypt_empty_string_returns_empty():
    assert encrypt_value("") == ""


def test_decrypt_empty_string_returns_empty():
    assert decrypt_value("") == ""


# ── No encryption key configured (plaintext fallback) ──


def test_encrypt_without_key_returns_plaintext():
    """When _get_fernet() returns None, encrypt should pass through."""
    with patch.object(enc_module, "_get_fernet", return_value=None):
        assert encrypt_value("my_secret") == "my_secret"


def test_decrypt_plaintext_without_prefix_returns_as_is():
    """Stored values without 'enc:' prefix are returned unchanged."""
    with patch.object(enc_module, "_get_fernet", return_value=None):
        assert decrypt_value("plain_token") == "plain_token"


def test_decrypt_encrypted_prefix_without_key_returns_as_is():
    """If value has 'enc:' prefix but no key, return stored value unchanged."""
    with patch.object(enc_module, "_get_fernet", return_value=None):
        result = decrypt_value("enc:someciphertext")
        assert result == "enc:someciphertext"


# ── With a real Fernet key ──


def _make_fernet():
    """Create a real Fernet instance for testing."""
    try:
        from cryptography.fernet import Fernet
        return Fernet(Fernet.generate_key())
    except ImportError:
        pytest.skip("cryptography package not installed")


def test_roundtrip_simple_string():
    f = _make_fernet()
    with patch.object(enc_module, "_get_fernet", return_value=f):
        encrypted = encrypt_value("hello world")
        assert encrypted.startswith("enc:")
        assert decrypt_value(encrypted) == "hello world"


def test_roundtrip_special_characters():
    f = _make_fernet()
    with patch.object(enc_module, "_get_fernet", return_value=f):
        special = "p@$$w0rd!#%^&*() unicode: \u00e9\u00e8\u00ea \U0001f600"
        encrypted = encrypt_value(special)
        assert decrypt_value(encrypted) == special


def test_roundtrip_long_string():
    f = _make_fernet()
    with patch.object(enc_module, "_get_fernet", return_value=f):
        long_str = "A" * 10000
        encrypted = encrypt_value(long_str)
        assert decrypt_value(encrypted) == long_str


def test_decrypt_with_wrong_key_returns_stored():
    """Decrypting with a different key should return stored value (not crash)."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        pytest.skip("cryptography package not installed")

    f1 = Fernet(Fernet.generate_key())
    f2 = Fernet(Fernet.generate_key())

    with patch.object(enc_module, "_get_fernet", return_value=f1):
        encrypted = encrypt_value("secret")

    with patch.object(enc_module, "_get_fernet", return_value=f2):
        result = decrypt_value(encrypted)
        # Should return the stored value (not crash), since decryption fails
        assert result == encrypted
