"""URL validation utilities — SSRF prevention for user-supplied URLs."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from config import settings
from libs.exceptions import ValidationError


def _is_blocked_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local


def validate_url(url: str) -> str:
    """Validate URL to prevent SSRF attacks."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("Only HTTP/HTTPS URLs are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("Invalid URL")

    # Allow the deterministic local scrape fixture host before DNS resolution.
    if settings.scrape_fixture_dir and hostname.lower() == "opentutor-e2e.local":
        return url

    # Block internal/private IPs
    try:
        if _is_blocked_ip(hostname):
            raise ValidationError("Internal URLs are not allowed")
    except ValueError:
        # Not an IP — hostname, allow but check for obvious internal hostnames
        blocked_hosts = {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "[::]",
            "[::1]",
            "metadata.google.internal",
        }
        if hostname.lower() in blocked_hosts:
            raise ValidationError("Internal URLs are not allowed")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            validate_hostname_dns(hostname)

    return url


def validate_hostname_dns(hostname: str) -> None:
    """Synchronously resolve hostnames for sync code paths and tests."""
    try:
        resolved = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationError("Hostname could not be resolved") from None

    for entry in resolved:
        resolved_ip = entry[4][0]
        if _is_blocked_ip(resolved_ip):
            raise ValidationError("Internal URLs are not allowed")


async def validate_url_dns(url: str) -> None:
    """Async DNS validation to avoid blocking the event loop."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return
    try:
        loop = asyncio.get_running_loop()
        resolved = await loop.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValidationError("Hostname could not be resolved") from None
    for entry in resolved:
        resolved_ip = entry[4][0]
        if _is_blocked_ip(resolved_ip):
            raise ValidationError("Internal URLs are not allowed")
