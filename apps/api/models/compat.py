"""Cross-database type compatibility layer.

Provides column types that work with both PostgreSQL and SQLite:
- CompatUUID: UUID (PG) or String(36) (SQLite)
- CompatJSONB: JSONB (PG) or JSON (SQLite, backed by TEXT + JSON1)
- CompatTSVECTOR: TSVECTOR (PG) or Text (SQLite, ignored — FTS5 used instead)
- CompatVector: pgvector Vector (PG) or Text (SQLite — sqlite-vec used via raw SQL)
"""

from sqlalchemy import Text, String, JSON
from sqlalchemy.types import TypeDecorator
import uuid as _uuid

from database import is_sqlite

if is_sqlite():
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

    CompatJSONB = JSON  # SQLite JSON1 extension via SQLAlchemy's JSON type
    CompatTSVECTOR = Text  # Placeholder; FTS5 virtual tables used instead

    class _TextVectorFactory:
        """Mimic pgvector's Vector(dim) API but return Text for SQLite."""
        def __call__(self, *args, **kwargs):
            return Text()
    CompatVector = _TextVectorFactory()  # CompatVector(1536) → Text()

else:
    from sqlalchemy.dialects.postgresql import UUID as _PGUUID, JSONB as _PGJSONB, TSVECTOR as _PGTSVECTOR
    try:
        from pgvector.sqlalchemy import Vector as _PGVector
    except ImportError:
        _PGVector = Text  # Graceful fallback if pgvector not installed

    class CompatUUID(TypeDecorator):
        """Native PG UUID."""
        impl = _PGUUID(as_uuid=True)
        cache_ok = True

        def process_bind_param(self, value, dialect):
            return value

        def process_result_value(self, value, dialect):
            return value

    CompatJSONB = _PGJSONB
    CompatTSVECTOR = _PGTSVECTOR
    CompatVector = _PGVector
