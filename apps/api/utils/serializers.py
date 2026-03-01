"""Shared serialization helpers for converting ORM models to dicts.

Eliminates the per-router ``_serialize_*()`` pattern by providing a single
``serialize_model()`` utility that handles UUID→str and datetime→isoformat
conversions consistently.

Usage:

    from utils.serializers import serialize_model

    return serialize_model(goal, extra={"linked_task_count": 5})
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


def _convert_value(value: Any) -> Any:
    """Convert a single value to its JSON-safe representation."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def serialize_model(
    obj: Any,
    fields: list[str] | None = None,
    *,
    exclude: set[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize an SQLAlchemy model instance to a JSON-safe dict.

    Args:
        obj: An ORM model instance.
        fields: Explicit list of attribute names to include. If None, all
                columns from ``__table__.columns`` are used.
        exclude: Set of field names to exclude.
        extra: Additional key-value pairs to merge into the result
               (e.g. computed fields like ``linked_task_count``).
    """
    exclude = exclude or set()

    if fields is None:
        # Auto-discover columns from SQLAlchemy model
        try:
            fields = [c.key for c in obj.__table__.columns if c.key not in exclude]
        except AttributeError:
            # Fallback: use __dict__ keys minus SQLAlchemy internals
            fields = [k for k in obj.__dict__ if not k.startswith("_") and k not in exclude]
    else:
        fields = [f for f in fields if f not in exclude]

    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(obj, field, None)
        result[field] = _convert_value(value)

    if extra:
        result.update(extra)

    return result
