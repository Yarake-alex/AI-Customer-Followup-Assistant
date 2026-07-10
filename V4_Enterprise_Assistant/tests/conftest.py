import importlib
import os
import sys

import pytest

# ── Module-level env (shared by all tests, never reads real .env) ──
os.environ["APP_ENV"] = "test"
os.environ["APP_ADMIN_USERNAME"] = "admin"
os.environ["APP_ACCESS_PASSWORD"] = "test-password"
os.environ["SESSION_SECRET"] = "test-secret-for-hmac-signing-1234567890abc"
os.environ["COOKIE_SECURE"] = "false"
os.environ["MAX_UPLOAD_SIZE_MB"] = "1"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["VECTOR_SEARCH_ENABLED"] = "false"


# ═══════════════════════════════════════════════════════════════
# Session-scoped fixtures — TF-IDF path (existing tests)
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def client(tmp_path_factory):
    """Session-scoped TestClient with TF-IDF fallback (default)."""
    tmp_dir = tmp_path_factory.mktemp("data")
    db_path = tmp_dir / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    # Reload app modules so settings are fresh — other test files may have
    # imported app.config before this fixture, caching a stale settings object.
    for mod in sorted(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]

    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def logged_in_client(client):
    """Pre-authenticated TF-IDF client."""
    resp = client.post("/auth/login", json={"password": "test-password"})
    assert resp.status_code == 200
    return client


# ═══════════════════════════════════════════════════════════════
# Function-scoped fixtures — Vector path (real chromadb + test embedding)
# ═══════════════════════════════════════════════════════════════

def _reload_app_modules() -> None:
    """Reload app submodules so new env vars / DB take effect."""
    for mod in sorted(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]


@pytest.fixture(scope="function")
def vector_client(tmp_path):
    """Function-scoped, fully isolated vector-search client.

    Each test gets:
      - a fresh SQLite database
      - a fresh ChromaDB directory
      - vector search enabled with test embedding provider

    Fails hard (no skip) when chromadb is missing — vectors tests must run.
    """
    # Verify chromadb is available (fail, don't skip)
    try:
        import chromadb  # noqa: F401
    except ImportError as exc:
        pytest.fail(
            f"chromadb is required for vector tests but failed to import.\n"
            f"Original error: {type(exc).__name__}: {exc}\n"
            f"Install: pip install -r requirements-vector.txt"
        )

    # Fresh paths per test function
    db_path = tmp_path / "test_vector.db"
    chroma_dir = tmp_path / "chroma_db"

    # Override env vars BEFORE re-importing app
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["VECTOR_SEARCH_ENABLED"] = "true"
    os.environ["EMBEDDING_PROVIDER"] = "test"
    os.environ["EMBEDDING_DIMENSION"] = "64"
    os.environ["CHROMA_PERSIST_DIR"] = str(chroma_dir)

    # Force fresh import of all app modules
    _reload_app_modules()

    from fastapi.testclient import TestClient
    from app.main import app

    tc = TestClient(app)

    # Login
    resp = tc.post("/auth/login", json={"password": "test-password"})
    assert resp.status_code == 200

    return tc


@pytest.fixture(scope="function")
def vector_client_dual_user(tmp_path, vector_client):
    """Returns (admin_client, user2_client) for dual-user isolation tests.

    admin_client is the default admin (from vector_client).
    user2_client is a second user with a separate login.
    """
    # Enable public registration temporarily to create second user
    from app.config import settings
    _prev = settings.ENABLE_PUBLIC_REGISTRATION
    settings.ENABLE_PUBLIC_REGISTRATION = True

    # Create second user
    resp = vector_client.post(
        "/auth/users",
        json={"username": "user2", "password": "user2-password"},
    )
    assert resp.status_code == 200, f"Failed to create user2: {resp.json()}"

    settings.ENABLE_PUBLIC_REGISTRATION = _prev

    # Create a second client logged in as user2
    # (re-login on the same TestClient is fine — cookie gets replaced)
    from fastapi.testclient import TestClient
    from app.main import app
    user2_tc = TestClient(app)
    resp = user2_tc.post(
        "/auth/login",
        json={"username": "user2", "password": "user2-password"},
    )
    assert resp.status_code == 200

    return vector_client, user2_tc
