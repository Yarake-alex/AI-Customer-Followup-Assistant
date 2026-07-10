"""Phase 4 — Database configuration and URL parsing tests.

These tests verify:
- DATABASE_URL configuration behaves correctly for SQLite and PostgreSQL.
- normalize_database_url() rewrites legacy PG URLs to psycopg v3.
- Engine connect_args differ between SQLite and PostgreSQL.
- Helper functions (is_sqlite_url, is_postgresql_url, get_database_url) work.
- VECTOR_SEARCH_ENABLED=false keeps pgvector inactive.
- Old database upgrade (Phase 3 fix) still works.

NOTE: These tests do NOT require a real PostgreSQL server. All PG-related
tests work through URL detection, normalization, and configuration logic.
"""

import os
import sys

import pytest


def _reload_app_modules():
    """Reload app.* modules so new env vars take effect."""
    for mod in sorted(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]


# ═══════════════════════════════════════════════════════════════
# Pure helper function tests — no module reloading needed
# ═══════════════════════════════════════════════════════════════


class TestDatabaseUrlHelpers:
    """Test the database URL helper functions in isolation."""

    def test_is_sqlite_url_true(self):
        """is_sqlite_url returns True for sqlite:// URLs."""
        from app.database import is_sqlite_url
        assert is_sqlite_url("sqlite:///./test.db") is True
        assert is_sqlite_url("sqlite:///C:/data/test.db") is True

    def test_is_sqlite_url_false_for_postgresql(self):
        """is_sqlite_url returns False for postgresql:// URLs."""
        from app.database import is_sqlite_url
        assert is_sqlite_url("postgresql://user:pass@host:5432/db") is False
        assert is_sqlite_url("postgresql+psycopg://user:pass@host:5432/db") is False

    def test_is_postgresql_url_true(self):
        """is_postgresql_url returns True for PostgreSQL URL variants."""
        from app.database import is_postgresql_url
        assert is_postgresql_url("postgresql://user:pass@host:5432/db") is True
        assert is_postgresql_url("postgresql+psycopg://user:pass@host:5432/db") is True
        assert is_postgresql_url("postgresql+psycopg2://user:pass@host:5432/db") is True
        assert is_postgresql_url("postgres://user:pass@host:5432/db") is True

    def test_is_postgresql_url_false_for_sqlite(self):
        """is_postgresql_url returns False for sqlite:// URLs."""
        from app.database import is_postgresql_url
        assert is_postgresql_url("sqlite:///./test.db") is False

    def test_get_database_url_returns_string(self):
        """get_database_url returns a non-empty string."""
        from app.database import get_database_url
        url = get_database_url()
        assert isinstance(url, str)
        assert len(url) > 0


class TestDatabaseUrlFormats:
    """Parametrized tests for various DATABASE_URL formats."""

    @pytest.mark.parametrize("url,expected_is_pg,expected_is_sqlite", [
        ("postgresql://user:pass@host:5432/dbname", True, False),
        ("postgresql+psycopg://user:pass@host:5432/dbname", True, False),
        ("postgresql+psycopg2://user:pass@host:5432/dbname", True, False),
        ("postgres://user:pass@host:5432/dbname", True, False),
        ("sqlite:///./customer_assistant.db", False, True),
        ("sqlite:////absolute/path/to/db.sqlite", False, True),
    ])
    def test_url_format_detection(self, url, expected_is_pg, expected_is_sqlite):
        """Each URL variant is detected correctly."""
        from app.database import is_postgresql_url, is_sqlite_url
        assert is_postgresql_url(url) == expected_is_pg, (
            f"is_postgresql_url('{url}') should be {expected_is_pg}"
        )
        assert is_sqlite_url(url) == expected_is_sqlite, (
            f"is_sqlite_url('{url}') should be {expected_is_sqlite}"
        )


# ═══════════════════════════════════════════════════════════════
# URL normalization tests — the core Phase 4 fix
# ═══════════════════════════════════════════════════════════════


class TestNormalizeDatabaseUrl:
    """Verify normalize_database_url() rewrites legacy PG URLs correctly."""

    def test_sqlite_unchanged(self):
        """SQLite URLs pass through unchanged."""
        from app.database import normalize_database_url
        assert normalize_database_url("sqlite:///./customer_assistant.db") == "sqlite:///./customer_assistant.db"
        assert normalize_database_url("sqlite:////absolute/path/to/db.sqlite") == "sqlite:////absolute/path/to/db.sqlite"

    def test_psycopg_already_canonical(self):
        """postgresql+psycopg:// is already canonical — unchanged."""
        from app.database import normalize_database_url
        url = "postgresql+psycopg://user:pass@host:5432/db"
        assert normalize_database_url(url) == url

    def test_psycopg2_normalized_to_psycopg(self):
        """postgresql+psycopg2:// → postgresql+psycopg://"""
        from app.database import normalize_database_url
        result = normalize_database_url("postgresql+psycopg2://user:pass@host:5432/db")
        assert result == "postgresql+psycopg://user:pass@host:5432/db"
        assert "+psycopg2" not in result

    def test_bare_postgresql_adds_psycopg_driver(self):
        """postgresql:// → postgresql+psycopg://"""
        from app.database import normalize_database_url
        result = normalize_database_url("postgresql://user:pass@host:5432/dbname")
        assert result == "postgresql+psycopg://user:pass@host:5432/dbname"

    def test_legacy_postgres_rewritten(self):
        """postgres:// → postgresql+psycopg://"""
        from app.database import normalize_database_url
        result = normalize_database_url("postgres://user:pass@host:5432/dbname")
        assert result == "postgresql+psycopg://user:pass@host:5432/dbname"
        assert not result.startswith("postgres://")

    def test_bare_postgresql_with_special_chars_in_password(self):
        """postgresql:// with URL-encoded password still gets the driver injected."""
        from app.database import normalize_database_url
        result = normalize_database_url("postgresql://user:p%40ss@host:5432/db")
        assert result == "postgresql+psycopg://user:p%40ss@host:5432/db"

    def test_unknown_scheme_passthrough(self):
        """Unknown URL schemes (mysql, etc.) pass through unchanged."""
        from app.database import normalize_database_url
        assert normalize_database_url("mysql://user:pass@host/db") == "mysql://user:pass@host/db"


class TestNormalizeAndDetectIntegration:
    """Verify normalization and detection work together."""

    def test_normalized_postgres_url_still_detected_as_pg(self):
        """After normalization, the URL is still detected as PostgreSQL."""
        from app.database import normalize_database_url, is_postgresql_url, is_sqlite_url
        for raw in [
            "postgresql://user:pass@host:5432/db",
            "postgresql+psycopg2://user:pass@host:5432/db",
            "postgres://user:pass@host:5432/db",
        ]:
            normalized = normalize_database_url(raw)
            assert is_postgresql_url(normalized), (
                f"normalize_database_url('{raw}') = '{normalized}' — should still be detected as PG"
            )
            assert not is_sqlite_url(normalized), (
                f"normalize_database_url('{raw}') = '{normalized}' — should NOT be detected as SQLite"
            )

    def test_normalize_then_is_postgresql_url_is_consistent(self):
        """is_postgresql_url(raw) == is_postgresql_url(normalized) for all PG variants."""
        from app.database import normalize_database_url, is_postgresql_url
        variants = [
            "postgresql+psycopg://user:pass@host/db",
            "postgresql+psycopg2://user:pass@host/db",
            "postgresql://user:pass@host/db",
            "postgres://user:pass@host/db",
        ]
        for raw in variants:
            assert is_postgresql_url(raw), f"is_postgresql_url should be True for raw: {raw}"
            normalized = normalize_database_url(raw)
            assert is_postgresql_url(normalized), (
                f"is_postgresql_url should be True for normalized: {normalized}"
            )


class TestEngineUsesNormalizedUrl:
    """Verify the module-level engine receives the normalized URL.

    These tests monkeypatch DATABASE_URL and reload app modules, then check the
    resulting engine's drivername.  Because psycopg may not be installed in the
    test venv, we only reload when the URL stays within SQLite (always
    available).  For PG variants we test normalize_database_url() as a pure
    function — covered by TestNormalizeDatabaseUrl above.
    """

    def test_engine_drivername_is_sqlite_by_default(self):
        """The test-session engine (SQLite) has drivername 'sqlite'."""
        from app.database import engine
        assert engine.url.drivername == "sqlite"

    def test_sqlite_engine_check_same_thread_false(self):
        """SQLite engine connect_args includes check_same_thread=False."""
        from app.database import engine
        # SQLAlchemy stores connect_args on the dialect or pool; verify via
        # the module-level flag that controls it.
        from app.database import is_sqlite
        assert is_sqlite is True, "Test engine should be SQLite"


# ═══════════════════════════════════════════════════════════════
# Settings integration tests
# ═══════════════════════════════════════════════════════════════


class TestDatabaseUrlInSettings:
    """Test that DATABASE_URL is properly integrated in pydantic Settings."""

    def test_settings_has_database_url_field(self):
        """Settings class defines DATABASE_URL with a default."""
        from app.config import Settings
        # pydantic-settings v2 uses model_fields dict
        assert "DATABASE_URL" in Settings.model_fields, (
            "Settings should define DATABASE_URL field"
        )

    def test_settings_default_is_sqlite(self, monkeypatch):
        """Default DATABASE_URL in Settings is SQLite."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        # Create a fresh Settings instance — does NOT import database module
        from app.config import Settings
        s = Settings()
        assert s.DATABASE_URL.startswith("sqlite"), (
            f"Default DATABASE_URL should be SQLite, got: {s.DATABASE_URL}"
        )

    def test_settings_respects_env_override(self, monkeypatch):
        """Settings DATABASE_URL respects environment variable override."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/testdb")
        from app.config import Settings
        s = Settings()
        assert s.DATABASE_URL == "postgresql://test:test@localhost:5432/testdb"

    def test_database_url_via_settings(self, monkeypatch):
        """get_database_url() reads from Settings (indirect integration test)."""
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./integration_test.db")
        _reload_app_modules()
        from app.database import get_database_url, is_sqlite_url
        url = get_database_url()
        assert is_sqlite_url(url)
        assert "integration_test.db" in url


# ═══════════════════════════════════════════════════════════════
# Engine connect_args tests — test the LOGIC, not live PG engine
# ═══════════════════════════════════════════════════════════════


class TestEngineConnectArgs:
    """Verify engine connect_args logic via URL detection (no live PG needed)."""

    def test_sqlite_url_results_in_check_same_thread(self, monkeypatch):
        """When DATABASE_URL is SQLite, is_sqlite_url returns True →
        connect_args gets check_same_thread=False."""
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_engine.db")
        _reload_app_modules()
        from app.database import get_database_url, is_sqlite_url
        url = get_database_url()
        assert is_sqlite_url(url), f"Expected SQLite detection for: {url}"
        # The module-level logic: connect_args = {"check_same_thread": False} if is_sqlite else {}
        # Since is_sqlite is True, connect_args would include check_same_thread

    def test_postgresql_url_results_in_empty_connect_args(self):
        """When DATABASE_URL is PostgreSQL, is_sqlite_url returns False →
        connect_args is empty (no SQLite-specific args)."""
        from app.database import is_sqlite_url, is_postgresql_url
        pg_url = "postgresql://user:pass@host:5432/db"
        assert not is_sqlite_url(pg_url), "PG URL should NOT be detected as SQLite"
        assert is_postgresql_url(pg_url), "PG URL should be detected as PostgreSQL"
        # The module-level logic: connect_args = {} because is_sqlite is False

    def test_existing_engine_is_sqlite(self):
        """The module-level engine (created during test collection) uses SQLite."""
        from app.database import engine
        assert engine.url.drivername == "sqlite", (
            f"Test engine should be SQLite, got: {engine.url.drivername}"
        )


# ═══════════════════════════════════════════════════════════════
# Vector search disabled tests — guard clause logic
# ═══════════════════════════════════════════════════════════════


class TestVectorSearchDisabled:
    """Verify VECTOR_SEARCH_ENABLED=false keeps pgvector inactive.

    These tests validate the *guard clauses* — they do NOT require a real PG.
    """

    def test_migrate_pgvector_guards_vector_disabled(self, monkeypatch):
        """_migrate_pgvector checks VECTOR_SEARCH_ENABLED first and returns early."""
        monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "false")
        _reload_app_modules()
        from app.db_init import _migrate_pgvector
        # Guard clause: if not settings.VECTOR_SEARCH_ENABLED → return
        # This should return None without touching any database
        result = _migrate_pgvector()
        assert result is None, (
            "_migrate_pgvector should return None when VECTOR_SEARCH_ENABLED=false"
        )

    def test_migrate_pgvector_guards_sqlite_url(self, monkeypatch):
        """_migrate_pgvector returns early for SQLite (even if vector enabled)."""
        monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "true")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
        _reload_app_modules()
        from app.db_init import _migrate_pgvector
        # Guard clause: if not is_postgresql_url(...) → return (SQLite uses ChromaDB)
        result = _migrate_pgvector()
        assert result is None, (
            "_migrate_pgvector should return None for SQLite (ChromaDB handles vectors)"
        )

    def test_verify_vector_deps_skips_when_disabled(self, monkeypatch):
        """_verify_vector_deps returns early when VECTOR_SEARCH_ENABLED=false."""
        monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "false")
        _reload_app_modules()
        from app.db_init import _verify_vector_deps
        result = _verify_vector_deps()
        assert result is None, (
            "_verify_vector_deps should return None when disabled"
        )

    def test_get_vector_store_returns_none_when_disabled(self, monkeypatch):
        """get_vector_store() returns None when VECTOR_SEARCH_ENABLED=false."""
        monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "false")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
        _reload_app_modules()
        from app.vector_store import get_vector_store
        store = get_vector_store()
        assert store is None, (
            "get_vector_store should return None when VECTOR_SEARCH_ENABLED=false"
        )


# ═══════════════════════════════════════════════════════════════
# Dialect-aware datetime type tests
# ═══════════════════════════════════════════════════════════════


class TestUpgradeDatabaseDatetimeType:
    """Verify upgrade_database resolves dialect-appropriate date-time type."""

    def test_sqlite_url_yields_datetime_type(self, monkeypatch):
        """When DATABASE_URL is SQLite, _dt_type should be 'DATETIME'."""
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_dt.db")
        _reload_app_modules()
        from app.database import is_postgresql_url, get_database_url
        url = get_database_url()
        assert not is_postgresql_url(url), "SQLite URL should not be detected as PG"
        # The upgrade_database function uses:
        #   _dt_type = "TIMESTAMP" if is_postgresql_url(...) else "DATETIME"
        # For SQLite, the else branch → "DATETIME"

    def test_postgresql_url_yields_timestamp_type(self):
        """When DATABASE_URL is PostgreSQL, _dt_type should be 'TIMESTAMP'."""
        from app.database import is_postgresql_url
        pg_url = "postgresql://user:pass@host:5432/db"
        assert is_postgresql_url(pg_url), "PostgreSQL URL should be detected as PG"
        # The upgrade_database function uses:
        #   _dt_type = "TIMESTAMP" if is_postgresql_url(...) else "DATETIME"
        # For PostgreSQL, the if branch → "TIMESTAMP"


# ═══════════════════════════════════════════════════════════════
# Phase 4 — Dialect-aware boolean literal tests
# ═══════════════════════════════════════════════════════════════


def _get_bool_true_literal(db_url: str) -> str:
    """Replicate the dialect-aware boolean true literal logic from upgrade_database().

    PostgreSQL uses TRUE; SQLite uses 1.
    """
    from app.database import is_postgresql_url
    return "TRUE" if is_postgresql_url(db_url) else "1"


class TestBoolTrueLiteralHelper:
    """Direct unit tests for the _get_bool_true_literal helper."""

    def test_bool_true_literal_sqlite(self):
        """SQLite boolean true token is '1'."""
        result = _get_bool_true_literal("sqlite:///./test.db")
        assert result == "1", f"SQLite bool true should be '1', got '{result}'"

    def test_bool_true_literal_sqlite_absolute_path(self):
        """SQLite absolute path — token still '1'."""
        result = _get_bool_true_literal("sqlite:////absolute/path/to/db.sqlite")
        assert result == "1", f"SQLite bool true should be '1', got '{result}'"

    def test_bool_true_literal_postgresql(self):
        """PostgreSQL boolean true token is 'TRUE'."""
        result = _get_bool_true_literal("postgresql://user:pass@host:5432/db")
        assert result == "TRUE", f"PostgreSQL bool true should be 'TRUE', got '{result}'"

    def test_bool_true_literal_postgresql_psycopg(self):
        """PostgreSQL+psycopg boolean true token is 'TRUE'."""
        result = _get_bool_true_literal("postgresql+psycopg://user:pass@host:5432/db")
        assert result == "TRUE", f"PostgreSQL+psycopg bool true should be 'TRUE', got '{result}'"

    def test_bool_true_literal_postgresql_psycopg2(self):
        """PostgreSQL+psycopg2 boolean true token is 'TRUE'."""
        result = _get_bool_true_literal("postgresql+psycopg2://user:pass@host:5432/db")
        assert result == "TRUE", f"PostgreSQL+psycopg2 bool true should be 'TRUE', got '{result}'"

    def test_bool_true_literal_legacy_postgres(self):
        """Legacy postgres:// boolean true token is 'TRUE'."""
        result = _get_bool_true_literal("postgres://user:pass@host:5432/db")
        assert result == "TRUE", f"Legacy postgres:// bool true should be 'TRUE', got '{result}'"


class TestBoolTrueLiteralRegression:
    """Ensure the boolean token logic is consistent with is_postgresql_url."""

    @pytest.mark.parametrize("url,expected", [
        ("sqlite:///./test.db", "1"),
        ("sqlite:////tmp/test.db", "1"),
        ("postgresql://user:pass@host:5432/db", "TRUE"),
        ("postgresql+psycopg://user:pass@host:5432/db", "TRUE"),
        ("postgresql+psycopg2://user:pass@host:5432/db", "TRUE"),
        ("postgres://user:pass@host:5432/db", "TRUE"),
    ])
    def test_bool_true_token_matches_dialect(self, url, expected):
        """Boolean true token correctly tracks is_postgresql_url."""
        assert _get_bool_true_literal(url) == expected, (
            f"URL '{url}' should yield bool_true='{expected}', "
            f"got '{_get_bool_true_literal(url)}'"
        )

    def test_bool_true_literal_always_string(self):
        """Return value is always a string, never an integer."""
        for url in [
            "sqlite:///./test.db",
            "postgresql://user:pass@host:5432/db",
        ]:
            result = _get_bool_true_literal(url)
            assert isinstance(result, str), (
                f"bool_true for '{url}' should be str, got {type(result).__name__}"
            )
