"""Tests for URL validation and SSRF prevention."""

import pytest

from libs.url_validation import _is_blocked_ip, validate_url, validate_hostname_dns
from libs.exceptions import ValidationError


class TestIsBlockedIp:
    def test_private_ip_blocked(self):
        assert _is_blocked_ip("192.168.1.1") is True
        assert _is_blocked_ip("10.0.0.1") is True
        assert _is_blocked_ip("172.16.0.1") is True

    def test_loopback_blocked(self):
        assert _is_blocked_ip("127.0.0.1") is True

    def test_link_local_blocked(self):
        assert _is_blocked_ip("169.254.1.1") is True

    def test_public_ip_allowed(self):
        assert _is_blocked_ip("8.8.8.8") is False
        assert _is_blocked_ip("1.1.1.1") is False


class TestValidateUrl:
    def test_valid_https_url(self):
        result = validate_url("https://example.com/path")
        assert result == "https://example.com/path"

    def test_valid_http_url(self):
        result = validate_url("http://example.com")
        assert result == "http://example.com"

    def test_rejects_ftp_scheme(self):
        with pytest.raises(ValidationError, match="HTTP/HTTPS"):
            validate_url("ftp://example.com")

    def test_rejects_file_scheme(self):
        with pytest.raises(ValidationError, match="HTTP/HTTPS"):
            validate_url("file:///etc/passwd")

    def test_rejects_empty_hostname(self):
        with pytest.raises(ValidationError):
            validate_url("http://")

    def test_rejects_localhost(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://localhost/admin")

    def test_rejects_127_0_0_1(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://127.0.0.1/admin")

    def test_rejects_metadata_google(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://metadata.google.internal/computeMetadata")

    def test_rejects_private_ip(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://192.168.1.1/admin")

    def test_rejects_10_network(self):
        with pytest.raises(ValidationError, match="Internal"):
            validate_url("http://10.0.0.1/secret")
