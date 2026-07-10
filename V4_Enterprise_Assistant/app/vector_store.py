"""Vector store abstraction.

Provides a unified interface over:
  - ChromaDB (SQLite / development — embedded, no extra service needed)
  - pgvector (PostgreSQL / production — reuses the existing PG database)

The factory returns a VectorStore or None (signalling a TF-IDF fallback).
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)


# ── Abstract interface ──

class VectorStore:
    """Protocol for vector indexing and similarity search."""

    def add_chunks(
        self,
        ids: List[int],
        embeddings: List[List[float]],
        metadatas: List[dict],
    ) -> None:
        raise NotImplementedError

    def search(
        self,
        query_embedding: List[float],
        user_id: int,
        top_k: int,
    ) -> List[int]:
        """Return ranked chunk IDs for a query embedding, scoped to a user."""
        raise NotImplementedError

    def delete_user_chunks(self, user_id: int) -> None:
        """Remove all vector entries for a user."""
        raise NotImplementedError

    def delete_filename_chunks(self, user_id: int, filename: str) -> None:
        """Remove vector entries for a specific file owned by a user."""
        raise NotImplementedError

    def count_user_chunks(self, user_id: int) -> int:
        """Return the number of indexed vectors for a user (for status checks)."""
        raise NotImplementedError

    def count_file_chunks(self, user_id: int, filename: str) -> int:
        """Return the number of indexed vectors for a specific file."""
        raise NotImplementedError


# ── ChromaDB implementation (SQLite / development) ──

class ChromaVectorStore(VectorStore):
    """ChromaDB-backed vector store.

    ChromaDB's PersistentClient stores everything under a single directory.
    We use one collection "rag_chunks" with cosine-distance HNSW.
    User isolation is handled via Chroma's ``where`` metadata filter.

    Uses ``upsert`` instead of ``add`` to avoid duplicate-ID errors when
    the same file is re-uploaded.
    """

    def __init__(self, persist_dir: str) -> None:
        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "chromadb is required for vector search with SQLite. "
                "Install it with: pip install -r requirements-vector.txt"
            )

        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="rag_chunks",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaDB vector store ready: {persist_dir}")

    def add_chunks(
        self,
        ids: List[int],
        embeddings: List[List[float]],
        metadatas: List[dict],
    ) -> None:
        if not ids:
            return
        # upsert: update if ID exists, insert if new — safe for re-uploads
        self._collection.upsert(
            ids=[str(cid) for cid in ids],
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def search(
        self,
        query_embedding: List[float],
        user_id: int,
        top_k: int,
    ) -> List[int]:
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"user_id": user_id},
        )
        if not results or not results["ids"] or not results["ids"][0]:
            return []
        return [int(cid) for cid in results["ids"][0]]

    def delete_user_chunks(self, user_id: int) -> None:
        # ChromaDB >=0.5 supports native where-delete — no get-then-delete needed
        self._collection.delete(where={"user_id": user_id})
        logger.info(f"ChromaDB: deleted chunks for user {user_id}")

    def delete_filename_chunks(self, user_id: int, filename: str) -> None:
        self._collection.delete(
            where={"$and": [{"user_id": user_id}, {"filename": filename}]}
        )
        logger.info(
            f"ChromaDB: deleted chunks for user {user_id}, file {filename}"
        )

    def count_user_chunks(self, user_id: int) -> int:
        existing = self._collection.get(
            where={"user_id": user_id},
        )
        return len(existing["ids"]) if (existing and existing["ids"]) else 0

    def count_file_chunks(self, user_id: int, filename: str) -> int:
        existing = self._collection.get(
            where={"$and": [{"user_id": user_id}, {"filename": filename}]},
        )
        return len(existing["ids"]) if (existing and existing["ids"]) else 0


# ── pgvector implementation (PostgreSQL / production) ──

class PgvectorStore(VectorStore):
    """pgvector-backed vector store.

    Stores embeddings directly in the ``document_chunks.embedding`` column.
    Uses the pgvector ``<=>`` (cosine distance) operator for similarity search.
    The embedding dimension is read from settings / detected at runtime.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        logger.info("pgvector vector store ready")

    def add_chunks(
        self,
        ids: List[int],
        embeddings: List[List[float]],
        metadatas: List[dict],
    ) -> None:
        if not ids:
            return

        from sqlalchemy import text
        from app.database import engine

        with engine.begin() as conn:
            for chunk_id, emb in zip(ids, embeddings):
                emb_str = "[" + ",".join(f"{v:.8f}" for v in emb) + "]"
                conn.execute(
                    text("""
                        UPDATE document_chunks
                        SET embedding = :emb::vector
                        WHERE id = :id
                    """),
                    {"id": chunk_id, "emb": emb_str},
                )

    def search(
        self,
        query_embedding: List[float],
        user_id: int,
        top_k: int,
    ) -> List[int]:
        from sqlalchemy import text
        from app.database import engine

        emb_str = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"

        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id
                    FROM document_chunks
                    WHERE user_id = :user_id
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> :emb::vector
                    LIMIT :top_k
                """),
                {"user_id": user_id, "emb": emb_str, "top_k": top_k},
            ).fetchall()

        return [row[0] for row in rows]

    def delete_user_chunks(self, user_id: int) -> None:
        from sqlalchemy import text
        from app.database import engine

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE document_chunks SET embedding = NULL WHERE user_id = :uid"),
                {"uid": user_id},
            )

    def delete_filename_chunks(self, user_id: int, filename: str) -> None:
        from sqlalchemy import text
        from app.database import engine

        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE document_chunks SET embedding = NULL "
                    "WHERE user_id = :uid AND filename = :fname"
                ),
                {"uid": user_id, "fname": filename},
            )

    def count_user_chunks(self, user_id: int) -> int:
        from sqlalchemy import text
        from app.database import engine

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM document_chunks "
                    "WHERE user_id = :uid AND embedding IS NOT NULL"
                ),
                {"uid": user_id},
            ).scalar()
        return row or 0

    def count_file_chunks(self, user_id: int, filename: str) -> int:
        from sqlalchemy import text
        from app.database import engine

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM document_chunks "
                    "WHERE user_id = :uid AND filename = :fname AND embedding IS NOT NULL"
                ),
                {"uid": user_id, "fname": filename},
            ).scalar()
        return row or 0


# ── Factory ──

_vector_store: Optional[VectorStore] = None
_vector_store_failed: bool = False


def get_vector_store() -> Optional[VectorStore]:
    """Return the vector store singleton, or None if unavailable.

    On first call:
      - SQLite  → ChromaVectorStore (persisted to ./data/chroma_db by default)
      - PostgreSQL → PgvectorStore (reuses the existing document_chunks table)

    Returns None when ``VECTOR_SEARCH_ENABLED`` is False or initialization fails,
    signalling callers to fall back to TF-IDF.
    """
    global _vector_store, _vector_store_failed

    if not settings.VECTOR_SEARCH_ENABLED:
        return None

    if _vector_store_failed:
        return None  # don't retry within the same process lifetime

    if _vector_store is not None:
        return _vector_store

    try:
        from app.database import DATABASE_URL, is_sqlite

        if is_sqlite:
            persist_dir = getattr(settings, "CHROMA_PERSIST_DIR", "./data/chroma_db")
            _vector_store = ChromaVectorStore(persist_dir=persist_dir)
        else:
            from app.database import SessionLocal
            _vector_store = PgvectorStore(SessionLocal)

        logger.info(f"Vector store initialized: {type(_vector_store).__name__}")
        return _vector_store

    except Exception as exc:
        logger.warning(
            f"Failed to initialize vector store: {exc}. "
            f"Falling back to TF-IDF retrieval."
        )
        _vector_store_failed = True
        return None
