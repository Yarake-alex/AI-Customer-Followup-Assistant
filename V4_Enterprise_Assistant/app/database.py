import os
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings


def get_database_url() -> str:
    """Return the configured DATABASE_URL.

    In test mode (APP_ENV=test) the Settings object respects env vars set
    before import, so monkeypatch-friendly.  In all other modes the value
    comes from the .env file or the DATABASE_URL environment variable.
    """
    return settings.DATABASE_URL


def is_sqlite_url(url: Optional[str] = None) -> bool:
    """Return True when *url* points to a SQLite database."""
    if url is None:
        url = get_database_url()
    return url.startswith("sqlite")


def is_postgresql_url(url: Optional[str] = None) -> bool:
    """Return True when *url* points to a PostgreSQL database."""
    if url is None:
        url = get_database_url()
    return url.startswith("postgresql") or url.startswith("postgres")


def normalize_database_url(url: str) -> str:
    """Normalize a DATABASE_URL so it is usable by SQLAlchemy create_engine.

    Rules (strategy: unify on psycopg v3):
      - ``sqlite://`` → unchanged.
      - ``postgresql+psycopg://`` → already canonical, unchanged.
      - ``postgresql+psycopg2://`` → rewritten to ``postgresql+psycopg://``.
      - ``postgresql://`` → driver added → ``postgresql+psycopg://``.
      - ``postgres://`` → scheme + driver rewritten → ``postgresql+psycopg://``.
      - Unknown schemes → passed through unchanged.

    This ensures that every PostgreSQL variant accepted by :func:`is_postgresql_url`
    actually produces a working engine after normalization, with no silent
    ``NoSuchModuleError`` from SQLAlchemy.
    """
    if url.startswith("sqlite"):
        return url

    # Already the canonical psycopg v3 form — nothing to do.
    if url.startswith("postgresql+psycopg://"):
        return url

    # psycopg2 → psycopg (v3).  Check BEFORE the bare "postgresql://" branch
    # so we don't double-insert the driver.
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("+psycopg2", "+psycopg", 1)

    # Bare postgresql:// — inject the psycopg v3 driver.
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)

    # Legacy postgres:// (SQLAlchemy has no "postgres" dialect).
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)

    # Unknown — pass through.
    return url


# ── Module-level engine (created once at import time) ──

_raw_url = get_database_url()
DATABASE_URL = normalize_database_url(_raw_url)
_is_sqlite = is_sqlite_url(DATABASE_URL)
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,  # helps with stale connections (PG pooled / restarted)
)

# Backward-compatible alias — other modules (e.g. vector_store) import this.
is_sqlite = _is_sqlite


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Set SQLite-specific pragmas on every new connection."""
    if not _is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
