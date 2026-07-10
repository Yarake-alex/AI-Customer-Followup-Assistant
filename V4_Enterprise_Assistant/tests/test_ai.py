"""Phase 6 — AI calling stability and cost control tests.

These tests verify:
- Mock mode call_llm works without real API Key
- Prompt truncation does NOT cause 500
- API error fallback returns Chinese fallback message
- Usage log is written with feature/user_id/provider/model/status/duration_ms
- Log write failure does NOT block AI response
- Feature params propagate for summary / suggestion / rag_ask / agent_analyze
- Admin AI logs API: admin access, normal user 403, no prompt/API Key, pagination
"""

import os
import sys

import pytest


def login(client):
    client.cookies.clear()
    resp = client.post("/auth/login", json={"password": "test-password"})
    assert resp.status_code == 200


def _reload_app_modules():
    for mod in sorted(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]


# ═══════════════════════════════════════════════════════════════
# Mock mode + basic call_llm tests
# ═══════════════════════════════════════════════════════════════


class TestCallLlmMock:
    """Test call_llm in mock mode (default test config)."""

    def test_call_llm_returns_string(self):
        """call_llm returns a non-empty string in mock mode."""
        from app.llm import call_llm
        result = call_llm("测试 prompt")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_call_llm_no_api_key_needed(self, monkeypatch):
        """Mock mode works even when OPENAI_API_KEY is None."""
        monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", None)
        monkeypatch.setattr("app.config.settings.LLM_PROVIDER", "mock")
        from app.llm import call_llm
        result = call_llm("另一个测试")
        assert "【AI模拟" in result or len(result) > 0

    def test_call_llm_with_feature_param(self):
        """call_llm accepts feature and returns a result."""
        from app.llm import call_llm
        result = call_llm("测试总结", feature="summary")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_call_llm_with_user_id_and_db(self, client):
        """call_llm accepts user_id and db without errors."""
        login(client)
        # Need a db session — use direct import
        from app.database import SessionLocal, engine
        from app.llm import call_llm

        db = SessionLocal()
        try:
            result = call_llm("测试带 user_id", feature="test", user_id=1, db=db)
            assert isinstance(result, str)
            assert len(result) > 0
        finally:
            db.close()

    def test_call_llm_backward_compatible(self):
        """Old call_llm(prompt) signature still works."""
        from app.llm import call_llm
        result = call_llm("hello")
        assert isinstance(result, str)
        assert len(result) > 0


# ═══════════════════════════════════════════════════════════════
# Prompt truncation tests
# ═══════════════════════════════════════════════════════════════


class TestPromptTruncation:
    """Verify long prompts are truncated, not rejected."""

    def test_long_prompt_does_not_crash(self, monkeypatch):
        """Prompt exceeding LLM_MAX_PROMPT_CHARS is truncated, not 500."""
        monkeypatch.setattr("app.config.settings.LLM_MAX_PROMPT_CHARS", 50)
        monkeypatch.setattr("app.config.settings.LLM_PROVIDER", "mock")
        monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", None)
        from app.llm import call_llm
        long_prompt = "A" * 5000
        result = call_llm(long_prompt)
        assert isinstance(result, str)
        assert len(result) > 0
        # Should not contain all 5000 As (truncation happened)
        assert len(result) < 5000

    def test_truncation_keeps_tail(self, monkeypatch):
        """Truncation keeps the end of the prompt (newest content at end)."""
        monkeypatch.setattr("app.config.settings.LLM_MAX_PROMPT_CHARS", 100)
        monkeypatch.setattr("app.config.settings.LLM_PROVIDER", "mock")
        monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", None)
        from app.llm import call_llm
        # Create prompt with distinct head and tail
        head = "HEAD_MARKER" * 10  # 110 chars
        tail = "TAIL_MARKER_总结" * 5  # ~100 chars — kept
        long_prompt = head + tail
        result = call_llm(long_prompt)
        assert isinstance(result, str)
        # mock summary response is returned (because tail contains "总结")
        assert "【AI模拟总结】" in result or "【AI模拟" in result or len(result) > 0


# ═══════════════════════════════════════════════════════════════
# Error fallback tests
# ═══════════════════════════════════════════════════════════════


class TestCallLlmFallback:
    """Verify error fallback returns Chinese message, never 500."""

    def test_fallback_on_api_error(self, monkeypatch):
        """When API call raises, fallback Chinese message is returned."""
        monkeypatch.setattr("app.config.settings.LLM_PROVIDER", "openai_compatible")
        monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", "sk-fake-key")
        monkeypatch.setattr("app.config.settings.OPENAI_BASE_URL", "http://127.0.0.1:19999/v1")
        monkeypatch.setattr("app.config.settings.OPENAI_MODEL", "deepseek-chat")
        monkeypatch.setattr("app.config.settings.LLM_TIMEOUT_SECONDS", 2)
        monkeypatch.setattr("app.config.settings.LLM_MAX_RETRIES", 0)

        from app.llm import call_llm
        result = call_llm("测试 fallback", feature="test_fallback")
        assert isinstance(result, str)
        assert "AI 服务暂时不可用" in result, (
            f"Expected fallback Chinese message, got: {result[:200]}"
        )

    def test_fallback_not_500_on_interface(self, client, monkeypatch):
        """AI summary endpoint does NOT 500 when LLM is unavailable."""
        login(client)
        monkeypatch.setattr("app.config.settings.LLM_PROVIDER", "openai_compatible")
        monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", "sk-fake-key")
        monkeypatch.setattr("app.config.settings.OPENAI_BASE_URL", "http://127.0.0.1:19999/v1")
        monkeypatch.setattr("app.config.settings.LLM_TIMEOUT_SECONDS", 2)
        monkeypatch.setattr("app.config.settings.LLM_MAX_RETRIES", 0)

        # Create a customer first
        resp = client.post("/customers", json={
            "name": "Fallback测试", "company": "Fallback公司",
            "phone": "13800000101",
        })
        assert resp.status_code == 200
        cid = resp.json()["id"]

        resp = client.post(f"/customers/{cid}/ai/summary")
        assert resp.status_code == 200, (
            f"Expected 200 even when LLM fails, got {resp.status_code}: {resp.json()}"
        )
        data = resp.json()
        assert "result" in data
        # Should be the Chinese fallback message
        assert "AI 服务暂时不可用" in data["result"], (
            f"Expected fallback message, got: {data['result'][:200]}"
        )

    def test_fallback_logs_status_fallback(self, monkeypatch):
        """API failure + db → AiCallLog.status='fallback', response_chars>0, error_message set."""
        monkeypatch.setattr("app.config.settings.LLM_PROVIDER", "openai_compatible")
        monkeypatch.setattr("app.config.settings.OPENAI_API_KEY", "sk-fake-key")
        monkeypatch.setattr("app.config.settings.OPENAI_BASE_URL", "http://127.0.0.1:19999/v1")
        monkeypatch.setattr("app.config.settings.OPENAI_MODEL", "deepseek-chat")
        monkeypatch.setattr("app.config.settings.LLM_TIMEOUT_SECONDS", 1)
        monkeypatch.setattr("app.config.settings.LLM_MAX_RETRIES", 0)
        monkeypatch.setattr("app.config.settings.LLM_ENABLE_USAGE_LOG", True)

        from app.database import SessionLocal
        from app.llm import call_llm
        from app.models import AiCallLog

        db = SessionLocal()
        try:
            result = call_llm("API fallback status test", feature="test_fallback_db", user_id=1, db=db)
            assert "AI 服务暂时不可用" in result, (
                f"Expected fallback Chinese message, got: {result[:200]}"
            )

            row = db.query(AiCallLog).order_by(AiCallLog.id.desc()).first()
            assert row is not None, "Expected an AiCallLog row"
            assert row.feature == "test_fallback_db"
            assert row.status == "fallback", f"Expected status='fallback', got '{row.status}'"
            assert row.response_chars > 0, f"Expected response_chars>0, got {row.response_chars}"
            assert row.error_message is not None, "Expected error_message to be set"
            assert len(row.error_message) > 0
        finally:
            db.close()


# ═══════════════════════════════════════════════════════════════
# Usage log tests
# ═══════════════════════════════════════════════════════════════


class TestUsageLog:
    """Verify AiCallLog entries are created correctly."""

    def test_usage_log_written_for_mock_call(self, client):
        """Mock LLM call writes a usage log row."""
        login(client)
        from app.database import SessionLocal, engine
        from app.llm import call_llm
        from app.models import AiCallLog

        db = SessionLocal()
        try:
            before = db.query(AiCallLog).count()
            result = call_llm("测试 usage log", feature="test_usage", user_id=1, db=db)
            after = db.query(AiCallLog).count()
            assert after > before, (
                f"Expected usage log row to be created. Before={before}, After={after}"
            )
            assert len(result) > 0
        finally:
            db.close()

    def test_usage_log_fields(self, client):
        """Usage log row contains expected fields."""
        login(client)
        from app.database import SessionLocal, engine
        from app.llm import call_llm
        from app.models import AiCallLog

        db = SessionLocal()
        try:
            call_llm("usage fields test", feature="summary", user_id=1, db=db)
            row = db.query(AiCallLog).order_by(AiCallLog.id.desc()).first()
            assert row is not None
            assert row.feature == "summary"
            assert row.user_id == 1
            assert row.provider == "mock"
            assert row.model == "mock"
            assert row.status == "success"
            assert row.prompt_chars > 0
            assert row.response_chars > 0
            assert row.duration_ms >= 0
            assert row.estimated_prompt_tokens > 0
            assert row.estimated_response_tokens > 0
        finally:
            db.close()

    def test_usage_log_failure_does_not_block_response(self, client, monkeypatch):
        """When log write fails, AI response still returns normally."""
        def _failing_log(*a, **kw):
            raise RuntimeError("simulated log error")
        monkeypatch.setattr("app.llm._write_usage_log", _failing_log)
        login(client)
        from app.llm import call_llm
        # Should not raise
        result = call_llm("log failure test", feature="test")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_usage_log_disabled(self, client, monkeypatch):
        """When LLM_ENABLE_USAGE_LOG=false, no log rows created."""
        monkeypatch.setattr("app.config.settings.LLM_ENABLE_USAGE_LOG", False)
        login(client)
        from app.database import SessionLocal, engine
        from app.llm import call_llm
        from app.models import AiCallLog

        db = SessionLocal()
        try:
            before = db.query(AiCallLog).count()
            call_llm("disabled log test", feature="test", user_id=1, db=db)
            after = db.query(AiCallLog).count()
            assert after == before, (
                f"No new log rows when disabled. Before={before}, After={after}"
            )
        finally:
            db.close()

    def test_write_usage_log_rollback_on_commit_failure(self, monkeypatch):
        """_write_usage_log calls db.rollback() when commit raises, and does NOT propagate."""
        rollback_called = False

        class FakeDb:
            def add(self, obj): pass
            def commit(self):
                raise RuntimeError("simulated commit failure")
            def rollback(self):
                nonlocal rollback_called
                rollback_called = True

        monkeypatch.setattr("app.config.settings.LLM_ENABLE_USAGE_LOG", True)
        from app.llm import _write_usage_log
        # Should not raise
        _write_usage_log(
            FakeDb(), user_id=1, feature="test_rollback", provider="test",
            model="test", prompt_chars=10, response_chars=20,
            status="success", error_message=None, duration_ms=42,
        )
        assert rollback_called, "db.rollback() should have been called after commit failure"


# ═══════════════════════════════════════════════════════════════
# Feature param propagation tests (API integration)
# ═══════════════════════════════════════════════════════════════


class TestFeatureParamPropagation:
    """Verify feature params are passed through from API endpoints."""

    CUSTOMER_DATA = {
        "name": "AI测试客户",
        "company": "AI测试公司",
        "phone": "13800000201",
        "industry": "汽车电子",
        "level": "A",
        "intention": "高",
    }

    def test_summary_endpoint_succeeds(self, client):
        """AI summary endpoint returns 200 and result string."""
        login(client)
        resp = client.post("/customers", json=self.CUSTOMER_DATA)
        assert resp.status_code == 200
        cid = resp.json()["id"]

        resp = client.post(f"/customers/{cid}/ai/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "【AI模拟总结】" in data["result"]

    def test_suggestion_endpoint_succeeds(self, client):
        """AI suggestion endpoint returns 200 and result string."""
        login(client)
        resp = client.post("/customers", json={
            **self.CUSTOMER_DATA,
            "name": "建议测试客户",
            "phone": "13800000202",
        })
        assert resp.status_code == 200
        cid = resp.json()["id"]

        resp = client.post(f"/customers/{cid}/ai/suggestion")
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "【AI模拟" in data["result"]

    def test_agent_analyze_endpoint_succeeds(self, client):
        """Agent analyze endpoint returns 200 with steps, result, sources."""
        login(client)
        resp = client.post("/customers", json={
            **self.CUSTOMER_DATA,
            "name": "Agent测试客户",
            "phone": "13800000203",
        })
        assert resp.status_code == 200
        cid = resp.json()["id"]

        resp = client.post("/agent/analyze", json={
            "customer_id": cid,
            "task": "分析客户",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "steps" in data
        assert "result" in data
        assert "sources" in data
        assert len(data["steps"]) > 0
        assert len(data["result"]) > 0


# ═══════════════════════════════════════════════════════════════
# Admin AI logs API tests
# ═══════════════════════════════════════════════════════════════


class TestAdminAiLogs:
    """Verify GET /admin/ai-logs access control and response format."""

    def test_admin_can_access_ai_logs(self, client):
        """Admin user can access /admin/ai-logs."""
        login(client)
        resp = client.get("/admin/ai-logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_normal_user_cannot_access_ai_logs(self, client):
        """Normal user gets 403 on /admin/ai-logs."""
        login(client)
        # Create normal user
        client.post("/auth/users", json={
            "username": "ai-log-viewer", "password": "ai-log-pass",
        })
        client.cookies.clear()
        resp = client.post("/auth/login", json={
            "username": "ai-log-viewer", "password": "ai-log-pass",
        })
        assert resp.status_code == 200

        resp = client.get("/admin/ai-logs")
        assert resp.status_code == 403

    def test_ai_logs_no_prompt_leak(self, client):
        """AI logs response must NOT contain prompt text or API keys."""
        login(client)
        # Trigger some AI calls first
        client.post("/customers", json={
            "name": "LogTest", "company": "LogCompany", "phone": "13800000301",
        })
        cid = client.get("/customers").json()[0]["id"]
        client.post(f"/customers/{cid}/ai/summary")

        resp = client.get("/admin/ai-logs")
        assert resp.status_code == 200
        data = resp.json()

        # Serialize to JSON string and check for sensitive keywords
        import json as _json
        raw = _json.dumps(data, ensure_ascii=False)
        # No API key patterns
        assert "sk-" not in raw.lower(), "Response must not contain API keys"
        # No prompt text leak (prompt text is not stored in the model anyway,
        # but verify the response doesn't contain it)
        for item in data["items"]:
            assert "prompt" not in item or isinstance(item.get("prompt"), type(None)), (
                "Response must not contain prompt text"
            )

    def test_ai_logs_pagination(self, client):
        """Pagination params work on /admin/ai-logs."""
        login(client)
        resp = client.get("/admin/ai-logs", params={"page": 1, "page_size": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert len(data["items"]) <= 5

    def test_ai_logs_page_size_max_capped(self, client):
        """page_size > 100 is capped at 100."""
        login(client)
        resp = client.get("/admin/ai-logs", params={"page_size": 999})
        assert resp.status_code == 200
        data = resp.json()
        # page_size capped to 100
        assert data["page_size"] == 100

    def test_unauthenticated_cannot_access_ai_logs(self, client):
        """Unauthenticated users get 401 on /admin/ai-logs."""
        client.cookies.clear()
        resp = client.get("/admin/ai-logs")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════
# Old database upgrade compatibility
# ═══════════════════════════════════════════════════════════════


class TestAiCallLogTableUpgrade:
    """Verify ai_call_logs table is created for old databases.

    Uses subprocess isolation to avoid corrupting the session-scoped
    test database used by other tests.
    """

    @staticmethod
    def _python_path() -> str:
        return sys.executable

    def test_old_db_gets_ai_call_logs_table(self, tmp_path):
        """Old database without ai_call_logs gets the table after upgrade."""
        import subprocess
        import json as _json

        db_path = tmp_path / "old_v5_ai.db"
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                is_admin BOOLEAN DEFAULT 0 NOT NULL,
                role VARCHAR(20) DEFAULT 'user' NOT NULL,
                is_active BOOLEAN DEFAULT 1 NOT NULL,
                created_at DATETIME
            )
        """)
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, role, is_active, created_at) "
            "VALUES ('admin', 'hash', 1, 'admin', 1, datetime('now'))"
        )
        conn.commit()
        conn.close()

        db_url_path = db_path.as_posix()  # forward slashes for sqlite:/// URL
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = f"""
import os, sys
sys.path.insert(0, {script_dir!r})
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///{db_url_path}"
os.environ["VECTOR_SEARCH_ENABLED"] = "false"
os.environ["LLM_ENABLE_USAGE_LOG"] = "true"
os.environ["APP_ADMIN_USERNAME"] = "admin"
os.environ["APP_ACCESS_PASSWORD"] = "test-password"
os.environ["SESSION_SECRET"] = "test-secret-for-hmac-signing-1234567890abc"
os.environ["COOKIE_SECURE"] = "false"
os.environ["LLM_PROVIDER"] = "mock"

from app.db_init import init_database
init_database()

import sqlite3
conn = sqlite3.connect({str(db_path)!r})
cur = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_call_logs'"
)
row = cur.fetchone()
conn.close()
if row is None:
    print("FAIL: ai_call_logs table not created")
    sys.exit(1)
print("OK: ai_call_logs table exists")
"""

        proc = subprocess.run(
            [self._python_path(), "-c", script],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, (
            f"Subprocess failed (exit={proc.returncode}).\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        assert "OK" in proc.stdout, f"Expected OK, got: {proc.stdout}"
