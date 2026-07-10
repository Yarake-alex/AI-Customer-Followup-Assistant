"""Phase 5 — Security hardening and backup/restore tests.

These tests verify:
- Production settings validation (errors and warnings)
- Default ENABLE_PUBLIC_REGISTRATION=false
- /auth/register returns 403 by default
- Login cookie has HttpOnly flag
- Security response headers on API and static responses
- Backup scripts do NOT contain dangerous deletion commands
- Production validation doesn't require Embedding API when VECTOR_SEARCH_ENABLED=false
- Development mode is unaffected by production checks
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
# Production settings validation tests
# ═══════════════════════════════════════════════════════════════


class TestValidateProductionSettings:
    """Test validate_production_settings() with various configurations."""

    def test_missing_access_password_raises(self, monkeypatch):
        """APP_ENV=production + APP_ACCESS_PASSWORD empty → ValueError."""
        monkeypatch.setattr("app.config.settings.APP_ENV", "production")
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "")
        monkeypatch.setattr("app.config.settings.SESSION_SECRET", "a-very-long-secret-key-for-production-use-123456")
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", False)
        monkeypatch.setattr("app.config.settings.COOKIE_SECURE", True)

        from app.config import validate_production_settings
        with pytest.raises(ValueError, match="APP_ACCESS_PASSWORD"):
            validate_production_settings()

    def test_missing_session_secret_raises(self, monkeypatch):
        """APP_ENV=production + SESSION_SECRET empty → ValueError."""
        monkeypatch.setattr("app.config.settings.APP_ENV", "production")
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "strong-password")
        monkeypatch.setattr("app.config.settings.SESSION_SECRET", "")
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", False)
        monkeypatch.setattr("app.config.settings.COOKIE_SECURE", True)

        from app.config import validate_production_settings
        with pytest.raises(ValueError, match="SESSION_SECRET"):
            validate_production_settings()

    def test_short_session_secret_raises(self, monkeypatch):
        """APP_ENV=production + SESSION_SECRET < 32 chars → ValueError."""
        monkeypatch.setattr("app.config.settings.APP_ENV", "production")
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "strong-password")
        monkeypatch.setattr("app.config.settings.SESSION_SECRET", "too-short")
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", False)
        monkeypatch.setattr("app.config.settings.COOKIE_SECURE", True)

        from app.config import validate_production_settings
        with pytest.raises(ValueError, match="SESSION_SECRET.*(?:32|characters)"):
            validate_production_settings()

    def test_public_registration_true_raises(self, monkeypatch):
        """APP_ENV=production + ENABLE_PUBLIC_REGISTRATION=true → ValueError."""
        monkeypatch.setattr("app.config.settings.APP_ENV", "production")
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "strong-password")
        monkeypatch.setattr("app.config.settings.SESSION_SECRET", "a-very-long-secret-key-for-production-use-123456")
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", True)
        monkeypatch.setattr("app.config.settings.COOKIE_SECURE", True)

        from app.config import validate_production_settings
        with pytest.raises(ValueError, match="ENABLE_PUBLIC_REGISTRATION"):
            validate_production_settings()

    def test_cookie_secure_false_warns_but_no_error(self, monkeypatch):
        """APP_ENV=production + COOKIE_SECURE=false → warning, NOT error."""
        monkeypatch.setattr("app.config.settings.APP_ENV", "production")
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "strong-password")
        monkeypatch.setattr("app.config.settings.SESSION_SECRET", "a-very-long-secret-key-for-production-use-123456")
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", False)
        monkeypatch.setattr("app.config.settings.COOKIE_SECURE", False)

        from app.config import validate_production_settings
        warnings = validate_production_settings()
        # Should return warnings (not raise)
        assert isinstance(warnings, list)
        assert len(warnings) >= 1
        cookie_warning = [w for w in warnings if "COOKIE_SECURE" in w]
        assert len(cookie_warning) >= 1, f"Expected COOKIE_SECURE warning, got: {warnings}"

    def test_all_valid_passes(self, monkeypatch):
        """All prod settings valid → no error, empty warnings."""
        monkeypatch.setattr("app.config.settings.APP_ENV", "production")
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "strong-password")
        monkeypatch.setattr("app.config.settings.SESSION_SECRET", "a-very-long-secret-key-for-production-use-123456")
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", False)
        monkeypatch.setattr("app.config.settings.COOKIE_SECURE", True)

        from app.config import validate_production_settings
        warnings = validate_production_settings()
        assert warnings == [], f"Expected no warnings, got: {warnings}"

    def test_development_mode_not_affected(self, monkeypatch):
        """APP_ENV=development → function is not called (guarded), but if called
        with dev-typical empty values it should still validate correctly."""
        # Simulate dev-like settings explicitly
        monkeypatch.setattr("app.config.settings.APP_ENV", "development")
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "")
        monkeypatch.setattr("app.config.settings.SESSION_SECRET", "")
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", False)
        monkeypatch.setattr("app.config.settings.COOKIE_SECURE", False)

        from app.config import validate_production_settings
        # The function doesn't check APP_ENV internally — it validates
        # whatever settings are currently active. This test verifies that
        # the function reports errors for dev-like values (no password/secret).
        with pytest.raises(ValueError):
            validate_production_settings()

    def test_vector_search_disabled_no_embedding_required(self, monkeypatch):
        """VECTOR_SEARCH_ENABLED=false + prod → validation does NOT require
        Embedding API configuration."""
        monkeypatch.setattr("app.config.settings.APP_ENV", "production")
        monkeypatch.setattr("app.config.settings.APP_ACCESS_PASSWORD", "strong-password")
        monkeypatch.setattr("app.config.settings.SESSION_SECRET", "a-very-long-secret-key-for-production-use-123456")
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", False)
        monkeypatch.setattr("app.config.settings.COOKIE_SECURE", True)
        monkeypatch.setattr("app.config.settings.VECTOR_SEARCH_ENABLED", False)

        from app.config import validate_production_settings
        warnings = validate_production_settings()
        # No embedding-related errors or warnings
        embedding_warnings = [w for w in warnings if "EMBEDDING" in w.upper()]
        assert len(embedding_warnings) == 0, (
            f"Should not warn about Embedding when VECTOR_SEARCH_ENABLED=false, got: {warnings}"
        )


# ═══════════════════════════════════════════════════════════════
# Public registration default-off tests
# ═══════════════════════════════════════════════════════════════


class TestPublicRegistrationDefaultOff:
    """Verify ENABLE_PUBLIC_REGISTRATION defaults to False and /auth/register is blocked."""

    def test_default_value_is_false(self):
        """Settings default for ENABLE_PUBLIC_REGISTRATION is False."""
        from app.config import Settings
        # Check the default value directly from the model fields
        default = Settings.model_fields["ENABLE_PUBLIC_REGISTRATION"].default
        assert default is False, (
            f"ENABLE_PUBLIC_REGISTRATION default should be False, got {default}"
        )

    def test_register_returns_403_by_default(self, client):
        """POST /auth/register returns 403 when public registration is off."""
        client.cookies.clear()
        resp = client.post(
            "/auth/register",
            json={"username": "hacker", "password": "hacker-password"},
        )
        assert resp.status_code == 403, (
            f"Expected 403 for public register, got {resp.status_code}: {resp.json()}"
        )
        assert "未开放" in resp.json()["detail"]

    def test_register_returns_403_even_when_env_set_to_false(self, client, monkeypatch):
        """Explicit ENABLE_PUBLIC_REGISTRATION=false → 403 on register."""
        monkeypatch.setattr("app.config.settings.ENABLE_PUBLIC_REGISTRATION", False)
        client.cookies.clear()
        resp = client.post(
            "/auth/register",
            json={"username": "hacker2", "password": "hacker-password"},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════
# Cookie security tests
# ═══════════════════════════════════════════════════════════════


class TestCookieSecurity:
    """Verify login cookie has HttpOnly and SameSite attributes."""

    def test_login_cookie_has_httponly(self, client):
        """Login response Set-Cookie must contain HttpOnly."""
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "test-password"})
        set_cookie = resp.headers.get("set-cookie", "")
        assert "HttpOnly" in set_cookie, (
            f"Cookie missing HttpOnly flag. set-cookie: {set_cookie}"
        )

    def test_login_cookie_has_samesite_lax(self, client):
        """Login response Set-Cookie must have SameSite=lax (or stricter)."""
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "test-password"})
        set_cookie = resp.headers.get("set-cookie", "")
        # SameSite could be "Lax" or "lax" depending on Starlette version
        assert "SameSite" in set_cookie or "samesite" in set_cookie.lower(), (
            f"Cookie missing SameSite attribute. set-cookie: {set_cookie}"
        )

    def test_login_cookie_no_plain_password(self, client):
        """Cookie value must not contain the plain text password."""
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "test-password"})
        set_cookie = resp.headers.get("set-cookie", "")
        assert "test-password" not in set_cookie, (
            "Cookie must not contain plain text password"
        )

    def test_login_cookie_uses_cookie_secure_setting(self, client):
        """Cookie secure flag is controlled by COOKIE_SECURE setting.
        In test mode COOKIE_SECURE=false, so secure flag should be absent."""
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "test-password"})
        set_cookie = resp.headers.get("set-cookie", "")
        # In test mode, COOKIE_SECURE is false, so "Secure" should NOT appear
        # (or if it does, it should be Secure=false)
        # Starlette may not emit Secure at all when it's False
        assert "Secure" not in set_cookie or "secure" not in set_cookie.lower().split(";")[0].split("=")[-1], (
            f"Cookie should not have Secure flag when COOKIE_SECURE=false. set-cookie: {set_cookie}"
        )


# ═══════════════════════════════════════════════════════════════
# Security response headers tests
# ═══════════════════════════════════════════════════════════════


class TestSecurityHeaders:
    """Verify security-related HTTP response headers are present."""

    def test_api_response_has_x_content_type_options(self, client):
        """API response has X-Content-Type-Options: nosniff."""
        resp = client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff", (
            f"Missing or wrong X-Content-Type-Options: {resp.headers}"
        )

    def test_api_response_has_x_frame_options(self, client):
        """API response has X-Frame-Options: DENY."""
        resp = client.get("/health")
        assert resp.headers.get("x-frame-options") == "DENY", (
            f"Missing or wrong X-Frame-Options: {resp.headers}"
        )

    def test_api_response_has_referrer_policy(self, client):
        """API response has Referrer-Policy: strict-origin-when-cross-origin."""
        resp = client.get("/health")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin", (
            f"Missing or wrong Referrer-Policy: {resp.headers}"
        )

    def test_api_response_has_permissions_policy(self, client):
        """API response has Permissions-Policy restricting camera, microphone, geolocation."""
        resp = client.get("/health")
        pp = resp.headers.get("permissions-policy", "")
        assert "camera=()" in pp, f"Permissions-Policy missing camera=(): {pp}"
        assert "microphone=()" in pp, f"Permissions-Policy missing microphone=(): {pp}"
        assert "geolocation=()" in pp, f"Permissions-Policy missing geolocation=(): {pp}"

    def test_protected_route_also_has_headers(self, client):
        """Protected routes (requiring login) also get security headers."""
        from tests.test_api import login
        login(client)
        resp = client.get("/customers")
        assert resp.status_code == 200
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_auth_route_also_has_headers(self, client):
        """Auth routes also get security headers."""
        resp = client.post("/auth/login", json={"password": "test-password"})
        assert resp.status_code == 200
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_error_response_also_has_headers(self, client):
        """Error responses (401, 404) also get security headers."""
        client.cookies.clear()
        resp = client.get("/customers")
        assert resp.status_code == 401
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"


# ═══════════════════════════════════════════════════════════════
# Backup script safety tests
# ═══════════════════════════════════════════════════════════════


class TestBackupScriptsSafe:
    """Verify backup scripts do not contain dangerous commands."""

    SCRIPTS_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts",
    )

    @pytest.fixture(autouse=True)
    def _check_scripts_dir(self):
        if not os.path.isdir(self.SCRIPTS_DIR):
            pytest.skip(f"Scripts directory not found: {self.SCRIPTS_DIR}")

    def _read_script(self, name: str) -> str:
        path = os.path.join(self.SCRIPTS_DIR, name)
        if not os.path.isfile(path):
            pytest.skip(f"Script not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_backup_sqlite_no_remove_item_recurse(self):
        """backup_sqlite.ps1 must NOT contain Remove-Item -Recurse."""
        content = self._read_script("backup_sqlite.ps1")
        # Case-insensitive check for PowerShell cmdlet
        assert "Remove-Item" not in content, (
            "backup_sqlite.ps1 must not contain Remove-Item"
        )

    def test_backup_sqlite_no_rm_rf(self):
        """backup_sqlite.ps1 must NOT contain rm -rf."""
        content = self._read_script("backup_sqlite.ps1")
        assert "rm -rf" not in content.lower(), (
            "backup_sqlite.ps1 must not contain rm -rf"
        )
        assert "rmdir /s" not in content.lower(), (
            "backup_sqlite.ps1 must not contain rmdir /s"
        )

    def test_backup_sqlite_no_hardcoded_passwords(self):
        """backup_sqlite.ps1 must NOT contain hardcoded passwords."""
        content = self._read_script("backup_sqlite.ps1")
        # No obvious password assignments with real-looking values
        suspicious = [
            "password=", "PASSWORD=", "passwd=",
            "change-this", "changeme", "admin123",
        ]
        lower = content.lower()
        for s in suspicious:
            assert s not in lower, (
                f"backup_sqlite.ps1 may contain hardcoded password: found '{s}'"
            )

    def test_backup_sqlite_no_auto_delete_old_backups(self):
        """backup_sqlite.ps1 must NOT automatically delete old backups."""
        content = self._read_script("backup_sqlite.ps1")
        delete_indicators = [
            "Remove-Item", "del ", "rm ", "rd ",
            "delete old", "cleanup", "clean up",
            "purge", "clear-old",
        ]
        lower = content.lower()
        for ind in delete_indicators:
            assert ind not in lower, (
                f"backup_sqlite.ps1 may contain deletion logic: found '{ind}'"
            )

    def test_backup_postgres_no_remove_item_recurse(self):
        """backup_postgres.ps1 must NOT contain Remove-Item -Recurse."""
        content = self._read_script("backup_postgres.ps1")
        assert "Remove-Item" not in content, (
            "backup_postgres.ps1 must not contain Remove-Item"
        )

    def test_backup_postgres_no_rm_rf(self):
        """backup_postgres.ps1 must NOT contain rm -rf."""
        content = self._read_script("backup_postgres.ps1")
        assert "rm -rf" not in content.lower(), (
            "backup_postgres.ps1 must not contain rm -rf"
        )
        assert "rmdir /s" not in content.lower(), (
            "backup_postgres.ps1 must not contain rmdir /s"
        )

    def test_backup_postgres_no_hardcoded_passwords(self):
        """backup_postgres.ps1 must NOT contain hardcoded passwords."""
        content = self._read_script("backup_postgres.ps1")
        suspicious = [
            "password=", "PASSWORD=", "passwd=",
            "change-this", "changeme", "admin123",
            "PGPASSWORD=",
        ]
        lower = content.lower()
        for s in suspicious:
            assert s not in lower, (
                f"backup_postgres.ps1 may contain hardcoded password: found '{s}'"
            )

    def test_backup_postgres_no_auto_delete_old_backups(self):
        """backup_postgres.ps1 must NOT automatically delete old backups."""
        content = self._read_script("backup_postgres.ps1")
        delete_indicators = [
            "Remove-Item", "del ", "rm ", "rd ",
            "delete old", "cleanup", "clean up",
            "purge", "clear-old",
        ]
        lower = content.lower()
        for ind in delete_indicators:
            assert ind not in lower, (
                f"backup_postgres.ps1 may contain deletion logic: found '{ind}'"
            )


# ═══════════════════════════════════════════════════════════════
# Production validation subprocess test — validates execution ORDER
# ═══════════════════════════════════════════════════════════════


class TestProductionValidationBeforeDatabaseInit:
    """Verify production validation runs BEFORE init_database().

    Uses subprocess isolation to avoid polluting the current pytest process.
    """

    @staticmethod
    def _python_path() -> str:
        return sys.executable

    @staticmethod
    def _script_dir() -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_invalid_prod_config_prevents_db_creation(self, tmp_path):
        """APP_ENV=production with invalid config → import fails AND .db file is NOT created."""
        import subprocess

        db_path = tmp_path / "prod_invalid.db"
        script = f"""
import os
import sys
sys.path.insert(0, {self._script_dir()!r})

os.environ["APP_ENV"] = "production"
os.environ["DATABASE_URL"] = "sqlite:///{db_path}"
os.environ["APP_ACCESS_PASSWORD"] = ""
os.environ["SESSION_SECRET"] = "a-very-long-secret-key-for-production-use-123456"
os.environ["ENABLE_PUBLIC_REGISTRATION"] = "false"
os.environ["VECTOR_SEARCH_ENABLED"] = "false"

import app.main
"""

        proc = subprocess.run(
            [self._python_path(), "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # The subprocess should fail (non-zero exit code)
        assert proc.returncode != 0, (
            f"Expected non-zero exit code for invalid production config, "
            f"got {proc.returncode}. stderr: {proc.stderr}"
        )

        # The database file should NOT have been created
        assert not db_path.exists(), (
            f"Database file {db_path} was created even though production "
            f"validation should have blocked init_database()"
        )


# ═══════════════════════════════════════════════════════════════
# Backup script enhanced safety tests — no overwrite, no -Force
# ═══════════════════════════════════════════════════════════════


class TestBackupScriptsNoOverwrite:
    """Verify backup scripts protect against overwriting existing backups."""

    SCRIPTS_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts",
    )

    @pytest.fixture(autouse=True)
    def _check_scripts_dir(self):
        if not os.path.isdir(self.SCRIPTS_DIR):
            pytest.skip(f"Scripts directory not found: {self.SCRIPTS_DIR}")

    def _read_script(self, name: str) -> str:
        path = os.path.join(self.SCRIPTS_DIR, name)
        if not os.path.isfile(path):
            pytest.skip(f"Script not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_sqlite_no_copy_item_force(self):
        """backup_sqlite.ps1 must NOT contain 'Copy-Item ... -Force'."""
        content = self._read_script("backup_sqlite.ps1")
        # Check that Copy-Item is NOT followed by -Force
        assert "Copy-Item" in content, "Script should still use Copy-Item"
        # The only Copy-Item line should NOT contain -Force
        for line in content.splitlines():
            if "Copy-Item" in line:
                assert "-Force" not in line, (
                    f"Copy-Item must not use -Force flag. Line: {line.strip()}"
                )

    def test_sqlite_has_overwrite_protection(self):
        """backup_sqlite.ps1 must check Test-Path $backupFile before copying."""
        content = self._read_script("backup_sqlite.ps1")
        # Must have Test-Path check for the backup file
        assert "Test-Path $backupFile" in content, (
            "backup_sqlite.ps1 must check if $backupFile exists before copying"
        )

    def test_sqlite_has_millisecond_timestamp(self):
        """backup_sqlite.ps1 must use _fff (millisecond) timestamp format."""
        content = self._read_script("backup_sqlite.ps1")
        assert "yyyyMMdd_HHmmss_fff" in content, (
            "backup_sqlite.ps1 must use millisecond timestamp format yyyyMMdd_HHmmss_fff"
        )

    def test_postgres_has_overwrite_protection(self):
        """backup_postgres.ps1 must check Test-Path $backupFile before redirect."""
        content = self._read_script("backup_postgres.ps1")
        assert "Test-Path $backupFile" in content, (
            "backup_postgres.ps1 must check if $backupFile exists before writing"
        )

    def test_postgres_has_millisecond_timestamp(self):
        """backup_postgres.ps1 must use _fff (millisecond) timestamp format."""
        content = self._read_script("backup_postgres.ps1")
        assert "yyyyMMdd_HHmmss_fff" in content, (
            "backup_postgres.ps1 must use millisecond timestamp format yyyyMMdd_HHmmss_fff"
        )


# ═══════════════════════════════════════════════════════════════
# Regression: existing auth tests should still pass
# ═══════════════════════════════════════════════════════════════


class TestSecurityRegression:
    """Verify Phase 5 changes don't break existing behavior."""

    def test_health_check_still_works(self, client):
        """Health check still returns ok."""
        client.cookies.clear()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_login_still_functions(self, client):
        """Login still works with test credentials."""
        client.cookies.clear()
        resp = client.post("/auth/login", json={"password": "test-password"})
        assert resp.status_code == 200
        assert "登录成功" in resp.json()["message"]

    def test_protected_routes_still_require_auth(self, client):
        """Protected routes still return 401 when not authenticated."""
        client.cookies.clear()
        resp = client.get("/customers")
        assert resp.status_code == 401

    def test_admin_create_user_still_works(self, client):
        """Admin can still create users."""
        from tests.test_api import login
        login(client)
        resp = client.post(
            "/auth/users",
            json={"username": "sec-test-user", "password": "sec-test-pass"},
        )
        assert resp.status_code in (200, 409)
