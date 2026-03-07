"""SQLite-only model type aliases.

`Compat*` names are kept for backwards compatibility with existing model code.
"""

import uuid as _uuid

from sqlalchemy import JSON, String, Text
from sqlalchemy.types import TypeDecorator


class CompatUUID(TypeDecorator):
    """Store UUIDs as 36-char strings in SQLite."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return _uuid.UUID(value)
        return value


CompatJSONB = JSON
CompatTSVECTOR = Text


class _TextVectorFactory:
    """Keep CompatVector(1536) call-shape while storing as TEXT in SQLite."""

    def __call__(self, *args, **kwargs):
        return Text()


CompatVector = _TextVectorFactory()
