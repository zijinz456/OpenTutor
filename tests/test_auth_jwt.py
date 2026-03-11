"""Tests for the JWT auth module (apps/api/services/auth/jwt.py)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from jose import jwt, JWTError

# ---------------------------------------------------------------------------
# Fake settings so the tests are fully self-contained
# ---------------------------------------------------------------------------
SECRET = "test-secret-key-for-unit-tests"  # pragma: allowlist secret
ALGORITHM = "HS256"
ACCESS_EXP_MINUTES = 30
REFRESH_EXP_DAYS = 7


@pytest.fixture(autouse=True)
def _patch_settings():
    """Patch config.settings used inside the jwt module."""
    fake = MagicMock()
    fake.jwt_secret_key = SECRET
    fake.jwt_algorithm = ALGORITHM
    fake.jwt_access_token_expire_minutes = ACCESS_EXP_MINUTES
    fake.jwt_refresh_token_expire_days = REFRESH_EXP_DAYS

    with patch("services.auth.jwt.settings", fake):
        yield


# Import *after* the conftest adds apps/api to sys.path
from services.auth.jwt import create_access_token, create_refresh_token, decode_token


# ---------------------------------------------------------------------------
# 1. create_access_token generates a valid JWT
# ---------------------------------------------------------------------------
class TestCreateAccessToken:
    def test_returns_valid_jwt(self):
        token = create_access_token("user-42")
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        assert payload["sub"] == "user-42"
        assert payload["type"] == "access"

    def test_has_expiration(self):
        token = create_access_token("user-1")
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        assert "exp" in payload


# ---------------------------------------------------------------------------
# 2. decode_token returns correct payload with sub and type
# ---------------------------------------------------------------------------
class TestDecodeToken:
    def test_returns_sub_and_type_for_access(self):
        token = create_access_token("alice")
        payload = decode_token(token)
        assert payload["sub"] == "alice"
        assert payload["type"] == "access"

    def test_returns_sub_and_type_for_refresh(self):
        token = create_refresh_token("bob")
        payload = decode_token(token)
        assert payload["sub"] == "bob"
        assert payload["type"] == "refresh"


# ---------------------------------------------------------------------------
# 3. Token has proper expiration window
# ---------------------------------------------------------------------------
class TestTokenExpiration:
    def test_access_token_expires_within_expected_window(self):
        before = datetime.now(timezone.utc)
        token = create_access_token("user-exp")
        after = datetime.now(timezone.utc)

        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        assert exp >= before + timedelta(minutes=ACCESS_EXP_MINUTES - 1)
        assert exp <= after + timedelta(minutes=ACCESS_EXP_MINUTES + 1)

    def test_refresh_token_expires_within_expected_window(self):
        before = datetime.now(timezone.utc)
        token = create_refresh_token("user-exp")
        after = datetime.now(timezone.utc)

        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        assert exp >= before + timedelta(days=REFRESH_EXP_DAYS - 1)
        assert exp <= after + timedelta(days=REFRESH_EXP_DAYS + 1)


# ---------------------------------------------------------------------------
# 4. Tampered token raises JWTError
# ---------------------------------------------------------------------------
class TestTamperedToken:
    def test_modified_payload_raises(self):
        token = create_access_token("legit-user")
        # Flip a character in the payload section (second segment)
        parts = token.split(".")
        tampered_payload = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
        tampered = f"{parts[0]}.{tampered_payload}.{parts[2]}"

        with pytest.raises(JWTError):
            decode_token(tampered)


# ---------------------------------------------------------------------------
# 5. Expired token raises JWTError
# ---------------------------------------------------------------------------
class TestExpiredToken:
    def test_expired_token_raises(self):
        # Manually craft a token that expired 10 minutes ago
        expired_payload = {
            "sub": "user-old",
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=10),
        }
        token = jwt.encode(expired_payload, SECRET, algorithm=ALGORITHM)

        with pytest.raises(JWTError):
            decode_token(token)


# ---------------------------------------------------------------------------
# 6. create_refresh_token has type "refresh"
# ---------------------------------------------------------------------------
class TestRefreshTokenType:
    def test_type_is_refresh(self):
        token = create_refresh_token("user-refresh")
        payload = decode_token(token)
        assert payload["type"] == "refresh"

    def test_access_type_is_access(self):
        token = create_access_token("user-access")
        payload = decode_token(token)
        assert payload["type"] == "access"


# ---------------------------------------------------------------------------
# 7. Wrong secret key fails to decode
# ---------------------------------------------------------------------------
class TestWrongSecretKey:
    def test_wrong_key_raises(self):
        token = create_access_token("user-secret")

        with pytest.raises(JWTError):
            jwt.decode(token, "wrong-secret-key", algorithms=[ALGORITHM])

    def test_wrong_key_via_patched_decode(self):
        """Encode with real secret, then swap the secret in settings and decode."""
        token = create_access_token("user-secret")

        wrong_settings = MagicMock()
        wrong_settings.jwt_secret_key = "completely-different-secret"  # pragma: allowlist secret
        wrong_settings.jwt_algorithm = ALGORITHM

        with patch("services.auth.jwt.settings", wrong_settings):
            with pytest.raises(JWTError):
                decode_token(token)
