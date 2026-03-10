"""Fernet symmetric encryption helpers for at-rest token protection.

Used by IntegrationCredential to encrypt OAuth access/refresh tokens before
storing them in the database.  When ENCRYPTION_KEY is not configured, falls
back to plaintext (development convenience — production should always set it).

Generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import logging

from config import settings

logger = logging.getLogger(__name__)

_fernet = None
_init_done = False


def _get_fernet():
    """Lazy-init Fernet cipher from settings.encryption_key.

    Only attempts initialization once; caches the result (including None
    for missing key / invalid key / missing cryptography package).
    """
    global _fernet, _init_done
    if _init_done:
        return _fernet

    key = settings.encryption_key
    if not key:
        logger.info(
            "ENCRYPTION_KEY not set — OAuth tokens stored in plaintext. "
            "Set ENCRYPTION_KEY in production for at-rest encryption."
        )
        _init_done = True
        return None

    try:
        from cryptography.fernet import Fernet

        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except ImportError:
        logger.warning("cryptography package not installed — encryption disabled")
    except (ValueError, TypeError) as exc:
        logger.error("Invalid ENCRYPTION_KEY: %s", exc)

    _init_done = True
    return _fernet


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value. Returns prefixed ciphertext or plaintext if no key."""
    if not plaintext:
        return plaintext

    f = _get_fernet()
    if f is None:
        return plaintext

    token = f.encrypt(plaintext.encode("utf-8"))
    return f"enc:{token.decode('utf-8')}"


def decrypt_value(stored: str) -> str:
    """Decrypt a stored value. Handles both encrypted (enc:...) and plaintext."""
    if not stored:
        return stored

    if not stored.startswith("enc:"):
        return stored  # plaintext fallback

    f = _get_fernet()
    if f is None:
        logger.warning("Cannot decrypt value: ENCRYPTION_KEY not configured")
        return stored

    try:
        from cryptography.fernet import InvalidToken
    except ImportError:
        InvalidToken = Exception  # type: ignore[misc,assignment]

    try:
        ciphertext = stored[4:]  # strip "enc:" prefix
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError, UnicodeDecodeError) as exc:
        logger.exception("Decryption failed: %s", exc)
        return stored
