"""Cross-database compatible column types for PostgreSQL + SQLite testing."""
import uuid as _uuid

from sqlalchemy import JSON, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID


class JSONB(TypeDecorator):
    """JSONB on PostgreSQL, JSON on other databases (SQLite)."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_JSONB())
        return dialect.type_descriptor(JSON())


class UUID(TypeDecorator):
    """UUID on PostgreSQL, CHAR(36) on other databases (SQLite)."""
    impl = String(36)
    cache_ok = True

    def __init__(self, as_uuid=True):
        super().__init__()
        self.as_uuid = as_uuid

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if isinstance(value, _uuid.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(str(value))
