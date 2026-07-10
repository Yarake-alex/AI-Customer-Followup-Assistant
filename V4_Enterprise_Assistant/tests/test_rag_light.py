"""Phase 7 — Lightweight RAG knowledge base management tests.

Tests for:
- GET /rag/documents enhanced (q, updated_at, preview)
- GET /rag/documents/{filename}/chunks
- POST /rag/documents/{filename}/reindex
- Cross-user isolation
- Backward compatibility (old tests still pass)
"""

import urllib.parse

import pytest


def login(client):
    client.cookies.clear()
    resp = client.post("/auth/login", json={"password": "test-password"})
    assert resp.status_code == 200


def _upload(client, filename="test.txt", content=b"Hello world. This is a test document for RAG."):
    login(client)
    resp = client.post("/rag/upload", files={"file": (filename, content, "text/plain")})
    assert resp.status_code == 200
    return resp.json()


# ═══════════════════════════════════════════════════════════════
# GET /rag/documents — enhanced list + q search
# ═══════════════════════════════════════════════════════════════


class TestRagDocumentsList:
    """Existing list structure preserved, enhanced with preview/updated_at."""

    def test_list_is_array(self, client):
        """GET /rag/documents still returns a list."""
        login(client)
        resp = client.get("/rag/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list), f"Expected list, got {type(data).__name__}"

    def test_fields_present(self, client):
        """Each item has filename, chunks, vector_indexed, updated_at, preview."""
        _upload(client, "fields_test.txt", b"Some content for field testing.")
        login(client)
        resp = client.get("/rag/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        item = [d for d in data if d["filename"] == "fields_test.txt"][0]
        assert "filename" in item
        assert "chunks" in item
        assert "vector_indexed" in item
        assert "updated_at" in item
        assert "preview" in item

    def test_preview_not_null_for_text(self, client):
        """Preview field is non-null for uploaded text docs."""
        _upload(client, "preview_test.txt", b"This is the first sentence. And this is the second sentence.")
        login(client)
        resp = client.get("/rag/documents")
        data = resp.json()
        item = [d for d in data if d["filename"] == "preview_test.txt"][0]
        assert item["preview"] is not None
        assert len(item["preview"]) > 0

    def test_updated_at_is_iso_string(self, client):
        """updated_at is an ISO-format string."""
        _upload(client, "updated_at_test.txt", b"Some content.")
        login(client)
        resp = client.get("/rag/documents")
        data = resp.json()
        item = [d for d in data if d["filename"] == "updated_at_test.txt"][0]
        assert item["updated_at"] is not None
        assert "T" in item["updated_at"]

    def test_q_search_matching(self, client):
        """q=xxx filters to matching filenames only."""
        _upload(client, "apple_doc.txt", b"Apple content.")
        _upload(client, "banana_doc.txt", b"Banana content.")
        _upload(client, "apple_pie.txt", b"Pie content.")
        login(client)
        resp = client.get("/rag/documents", params={"q": "apple"})
        assert resp.status_code == 200
        data = resp.json()
        filenames = [d["filename"] for d in data]
        assert "apple_doc.txt" in filenames
        assert "apple_pie.txt" in filenames
        assert "banana_doc.txt" not in filenames

    def test_q_search_no_match(self, client):
        """q with no matches returns empty list, not error."""
        _upload(client, "only_file.txt", b"Content.")
        login(client)
        resp = client.get("/rag/documents", params={"q": "nonexistent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    def test_q_search_empty_returns_all(self, client):
        """q='' or no q returns all documents."""
        _upload(client, "doc_a.txt", b"A.")
        _upload(client, "doc_b.txt", b"B.")
        login(client)
        resp = client.get("/rag/documents")
        assert resp.status_code == 200
        all_count = len(resp.json())
        resp2 = client.get("/rag/documents", params={"q": ""})
        assert resp2.status_code == 200
        assert len(resp2.json()) == all_count


# ═══════════════════════════════════════════════════════════════
# Cross-user isolation for q search
# ═══════════════════════════════════════════════════════════════


class TestRagDocumentsCrossUser:
    """Filename search must not leak across users."""

    def test_q_search_isolated(self, client):
        """User A's q search doesn't see User B's files."""
        login(client)
        _upload(client, "user_a_file.txt", b"User A content.")

        # Create user B
        client.post("/auth/users", json={"username": "rag-q-b", "password": "rag-q-b-pass"})

        # Login as user B and upload manually (NOT via _upload, which re-logs admin)
        client.cookies.clear()
        resp = client.post("/auth/login", json={"username": "rag-q-b", "password": "rag-q-b-pass"})
        assert resp.status_code == 200
        resp = client.post(
            "/rag/upload",
            files={"file": ("user_b_file.txt", b"User B content.", "text/plain")},
        )
        assert resp.status_code == 200

        # User B searches for user A's file — should not find it
        resp = client.get("/rag/documents", params={"q": "user_a"})
        assert resp.status_code == 200
        data = resp.json()
        filenames = [d["filename"] for d in data]
        assert "user_a_file.txt" not in filenames


# ═══════════════════════════════════════════════════════════════
# GET /rag/documents/{filename}/chunks
# ═══════════════════════════════════════════════════════════════


class TestRagFileChunks:
    """View chunks for a single file."""

    def test_chunks_returns_correct_structure(self, client):
        """Response has filename and chunks[] with chunk_index, content, created_at."""
        _upload(client, "chunks_test.txt", b"First chunk here. Second chunk is also here. Third one.")
        login(client)
        encoded = urllib.parse.quote("chunks_test.txt", safe="")
        resp = client.get(f"/rag/documents/{encoded}/chunks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "chunks_test.txt"
        assert isinstance(data["chunks"], list)
        assert len(data["chunks"]) >= 1
        c = data["chunks"][0]
        assert "chunk_index" in c
        assert "content" in c
        assert "created_at" in c

    def test_chunks_sorted_by_index(self, client):
        """Chunks are returned in chunk_index ascending order."""
        content = "A" * 500 + " B" * 500 + " C" * 500  # 3 chunks
        _upload(client, "sorted_test.txt", content.encode())
        login(client)
        encoded = urllib.parse.quote("sorted_test.txt", safe="")
        resp = client.get(f"/rag/documents/{encoded}/chunks")
        assert resp.status_code == 200
        data = resp.json()
        indices = [c["chunk_index"] for c in data["chunks"]]
        assert indices == sorted(indices), f"Chunks should be sorted by index, got {indices}"

    def test_chunks_file_not_found_404(self, client):
        """Non-existent file returns 404."""
        login(client)
        resp = client.get("/rag/documents/nonexistent_file.txt/chunks")
        assert resp.status_code == 404

    def test_chunks_cross_user_isolation(self, client):
        """User A's chunks are not visible to User B."""
        login(client)
        _upload(client, "secret_chunks.txt", b"Secret content only for admin.")

        client.post("/auth/users", json={"username": "rag-chunk-b", "password": "rag-chunk-b-pass"})
        client.cookies.clear()
        resp = client.post("/auth/login", json={"username": "rag-chunk-b", "password": "rag-chunk-b-pass"})
        assert resp.status_code == 200

        encoded = urllib.parse.quote("secret_chunks.txt", safe="")
        resp = client.get(f"/rag/documents/{encoded}/chunks")
        assert resp.status_code == 404, (
            f"User B should get 404 for User A's file, got {resp.status_code}"
        )


# ═══════════════════════════════════════════════════════════════
# POST /rag/documents/{filename}/reindex
# ═══════════════════════════════════════════════════════════════


class TestRagFileReindex:
    """Single-file vector reindex endpoint."""

    def test_reindex_vector_disabled_returns_false(self, client):
        """When VECTOR_SEARCH_ENABLED=false, returns reindexed=false, not 500."""
        _upload(client, "reindex_disabled.txt", b"Content for reindex test.")
        login(client)
        encoded = urllib.parse.quote("reindex_disabled.txt", safe="")
        resp = client.post(f"/rag/documents/{encoded}/reindex")
        assert resp.status_code == 200, (
            f"Expected 200 even when vector disabled, got {resp.status_code}: {resp.json()}"
        )
        data = resp.json()
        assert data["reindexed"] is False
        assert "向量搜索未启用" in data["message"]
        assert data["filename"] == "reindex_disabled.txt"
        assert data["chunks"] >= 1

    def test_reindex_file_not_found_404(self, client):
        """Non-existent file returns 404, not 500."""
        login(client)
        resp = client.post("/rag/documents/no_such_file.txt/reindex")
        assert resp.status_code == 404

    def test_reindex_cross_user_not_found(self, client):
        """User B gets 404 trying to reindex User A's file."""
        login(client)
        _upload(client, "admin_reindex.txt", b"Admin file for reindex test.")

        client.post("/auth/users", json={"username": "rag-rix-b", "password": "rag-rix-b-pass"})
        client.cookies.clear()
        resp = client.post("/auth/login", json={"username": "rag-rix-b", "password": "rag-rix-b-pass"})
        assert resp.status_code == 200

        encoded = urllib.parse.quote("admin_reindex.txt", safe="")
        resp = client.post(f"/rag/documents/{encoded}/reindex")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# Vector-enabled single-file reindex (requires vector_client fixture)
# ═══════════════════════════════════════════════════════════════


class TestRagFileReindexVector:
    """Single-file reindex with vector search enabled."""

    def test_reindex_single_file_vector(self, vector_client):
        """Single file reindex succeeds and per-file counts update."""
        vector_client.post(
            "/rag/upload",
            files={"file": ("single_reindex.txt", b"Content that will be reindexed individually.")},
        )

        encoded = urllib.parse.quote("single_reindex.txt", safe="")
        resp = vector_client.post(f"/rag/documents/{encoded}/reindex")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reindexed"] is True
        assert data["chunks"] >= 1
        assert "重新索引完成" in data["message"]

        # Verify per-file counts
        docs = vector_client.get("/rag/documents").json()
        item = [d for d in docs if d["filename"] == "single_reindex.txt"][0]
        assert item["vector_indexed"] == item["chunks"]

    def test_reindex_single_file_isolated(self, vector_client, vector_client_dual_user):
        """Reindexing file A doesn't affect file B or user B."""
        admin, user2 = vector_client_dual_user

        admin.post(
            "/rag/upload",
            files={"file": ("admin_rix.txt", b"Admin file for isolated reindex test.")},
        )
        user2.post(
            "/rag/upload",
            files={"file": ("user2_rix.txt", b"User2 file that should not be affected.")},
        )

        # Admin reindexes only their file
        encoded = urllib.parse.quote("admin_rix.txt", safe="")
        resp = admin.post(f"/rag/documents/{encoded}/reindex")
        assert resp.status_code == 200
        assert resp.json()["reindexed"] is True

        # User2's file should still be indexed
        user2_docs = user2.get("/rag/documents").json()
        u2_item = [d for d in user2_docs if d["filename"] == "user2_rix.txt"][0]
        assert u2_item["vector_indexed"] == u2_item["chunks"]
