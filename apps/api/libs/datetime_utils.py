"""Shared datetime utilities."""

from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    """Ensure a datetime is in UTC. Assumes naive datetimes are UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utcnow() -> datetime:
    """Return the current time in UTC (timezone-aware)."""
    return datetime.now(timezone.utc)
