"""Tests for libs/url_validation.py — SSRF prevention."""

import pytest
from libs.url_validation import validate_url, _is_blocked_ip, validate_hostname_dns
from libs.exceptions import ValidationError


class TestIsBlockedIp:
    def test_loopback(self):
        assert _is_blocked_ip("127.0.0.1") is True

    def test_private_10(self):
        assert _is_blocked_ip("10.0.0.1") is True

    def test_private_192(self):
        assert _is_blocked_ip("192.168.1.1") is True

    def test_link_local(self):
        assert _is_blocked_ip("169.254.1.1") is True

    def test_public_ip(self):
        assert _is_blocked_ip("8.8.8.8") is False


class TestValidateUrl:
    def test_valid_https(self):
        result = validate_url("https://example.com/path")
        assert result == "https://example.com/path"

    def test_rejects_ftp(self):
        with pytest.raises(ValidationError, match="HTTP"):
            validate_url("ftp://example.com")

    def test_rejects_no_scheme(self):
        with pytest.raises(ValidationError):
            validate_url("not-a-url")

    def test_rejects_localhost(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://localhost/secret")

    def test_rejects_127(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://127.0.0.1/admin")

    def test_rejects_metadata_endpoint(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://metadata.google.internal/computeMetadata")

    def test_rejects_private_ip(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://10.0.0.1/internal")

    def test_rejects_empty_hostname(self):
        with pytest.raises(ValidationError, match="Invalid"):
            validate_url("http://")


class TestValidateHostnameDns:
    def test_resolves_public_host(self):
        validate_hostname_dns("example.com")

    def test_rejects_unresolvable(self):
        with pytest.raises(ValidationError, match="resolved"):
            validate_hostname_dns("this-domain-does-not-exist-12345.invalid")
