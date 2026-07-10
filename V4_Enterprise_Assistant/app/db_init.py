import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.config import settings
from app.auth import ensure_bootstrap_admin
# 确保所有 SQLAlchemy 模型被导入并注册到 Base.metadata
from app import models

logger = logging.getLogger(__name__)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return False
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    )


def ensure_default_user() -> int:
    username = settings.APP_ADMIN_USERNAME or "admin"
    password = settings.APP_ACCESS_PASSWORD or "__local_dev_password__"

    with Session(engine) as db:
        user = ensure_bootstrap_admin(db, username=username, password=password)
        return user.id


def upgrade_database() -> None:
    # Resolve the dialect-appropriate date-time column type.
    # SQLite uses DATETIME; PostgreSQL uses TIMESTAMP.
    from app.database import is_postgresql_url, get_database_url
    _dt_type = "TIMESTAMP" if is_postgresql_url(get_database_url()) else "DATETIME"
    # PostgreSQL boolean fields use TRUE/FALSE; SQLite uses 1/0
    _bool_true = "TRUE" if is_postgresql_url(get_database_url()) else "1"

    # ── Phase 3: add user role/is_active columns FIRST ──
    # Must run before ensure_default_user(), because ensure_bootstrap_admin()
    # uses the User ORM which needs these columns to exist.
    with engine.begin() as conn:
        if not column_exists("users", "role"):
            conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user'"))
            conn.execute(
                text(f"UPDATE users SET role = 'admin' WHERE is_admin = {_bool_true}")
            )
            conn.execute(
                text("UPDATE users SET role = 'user' WHERE role IS NULL")
            )

        if not column_exists("users", "is_active"):
            conn.execute(text(f"ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT {_bool_true}"))
            conn.execute(
                text(f"UPDATE users SET is_active = {_bool_true} WHERE is_active IS NULL")
            )

    # Now safe to use ORM — users table has all columns
    default_user_id = ensure_default_user()

    with engine.begin() as conn:
        if not column_exists("customers", "cooperation_status"):
            conn.execute(
                text("ALTER TABLE customers ADD COLUMN cooperation_status VARCHAR(20)")
            )

        if not column_exists("customers", "source"):
            conn.execute(text("ALTER TABLE customers ADD COLUMN source VARCHAR(100)"))

        if not column_exists("customers", "remark"):
            conn.execute(text("ALTER TABLE customers ADD COLUMN remark TEXT"))

        if not column_exists("customers", "last_followup_at"):
            conn.execute(text(f"ALTER TABLE customers ADD COLUMN last_followup_at {_dt_type}"))

        if not column_exists("customers", "next_followup_at"):
            conn.execute(text(f"ALTER TABLE customers ADD COLUMN next_followup_at {_dt_type}"))

        if not column_exists("customers", "followup_status"):
            conn.execute(text("ALTER TABLE customers ADD COLUMN followup_status VARCHAR(20) DEFAULT '待跟进'"))
            conn.execute(
                text("UPDATE customers SET followup_status = '待跟进' WHERE followup_status IS NULL")
            )

        if not column_exists("customers", "user_id"):
            conn.execute(text("ALTER TABLE customers ADD COLUMN user_id INTEGER"))
            conn.execute(
                text("UPDATE customers SET user_id = :user_id WHERE user_id IS NULL"),
                {"user_id": default_user_id},
            )

        if not column_exists("document_chunks", "user_id"):
            conn.execute(text("ALTER TABLE document_chunks ADD COLUMN user_id INTEGER"))
            conn.execute(
                text("UPDATE document_chunks SET user_id = :user_id WHERE user_id IS NULL"),
                {"user_id": default_user_id},
            )

    # ── Phase 6: ai_call_logs table ──
    inspector = inspect(engine)
    if "ai_call_logs" not in inspector.get_table_names():
        # table doesn't exist at all — create it
        from app.models import AiCallLog
        AiCallLog.__table__.create(bind=engine, checkfirst=True)



def create_indexes() -> None:
    """为已有数据库幂等补建索引。"""
    with engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_customers_user_id ON customers (user_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_followups_customer_id ON followups (customer_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_document_chunks_user_id ON document_chunks (user_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_document_chunks_filename ON document_chunks (filename)")
        )

    # ── Phase 6: ai_call_logs indexes ──
    with engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_ai_call_logs_user_id ON ai_call_logs (user_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_ai_call_logs_feature ON ai_call_logs (feature)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_ai_call_logs_status ON ai_call_logs (status)")
        )


def _resolve_pgvector_dimension() -> int:
    """Resolve the pgvector embedding dimension for PostgreSQL.

    - EMBEDDING_DIMENSION > 0 → use it verbatim.
    - EMBEDDING_DIMENSION = 0 → probe the embedding service to detect the real dimension.
      If probing fails, raise with a clear message (no silent default).
    """
    configured = settings.EMBEDDING_DIMENSION
    if configured and configured > 0:
        return configured

    # Auto-detect by probing the embedding service
    try:
        from app.embeddings import get_embedding_service
        emb = get_embedding_service()
        detected = emb.dimension
        logger.info(f"Probed embedding dimension for pgvector: {detected}")
        return detected
    except Exception as exc:
        raise RuntimeError(
            f"EMBEDDING_DIMENSION is 0 (auto) but cannot probe embedding model on PostgreSQL. "
            f"Set EMBEDDING_DIMENSION explicitly to match your embedding model (e.g. 1024). "
            f"Probe error: {exc}"
        ) from exc


def _migrate_pgvector() -> None:
    """Enable pgvector extension and add embedding column on PostgreSQL.

    Only runs when ALL of the following are true:
      - VECTOR_SEARCH_ENABLED is True
      - The database is PostgreSQL (not SQLite)
    """
    if not settings.VECTOR_SEARCH_ENABLED:
        return  # vector search disabled — nothing to do

    from app.database import get_database_url, is_postgresql_url

    db_url = get_database_url()
    if not is_postgresql_url(db_url):
        return  # SQLite — ChromaDB handles vectors separately

    vector_dim = _resolve_pgvector_dimension()

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        if column_exists("document_chunks", "embedding"):
            # Validate existing column dimension matches configured dimension
            inspector = inspect(engine)
            cols = inspector.get_columns("document_chunks")
            for col in cols:
                if col["name"] == "embedding":
                    col_type = str(col["type"])
                    # pgvector type shows as e.g. "vector(1024)" or "USER-DEFINED"
                    if str(vector_dim) not in col_type and "vector" in col_type.lower():
                        logger.warning(
                            f"Existing embedding column type is '{col_type}' but configured "
                            f"dimension is {vector_dim}. Dimension mismatch may cause errors."
                        )
                    break
        else:
            conn.execute(
                text(f"ALTER TABLE document_chunks ADD COLUMN embedding vector({vector_dim})")
            )
            logger.info(f"Created embedding column with dimension {vector_dim}")

        # Create HNSW index for cosine similarity search (if not exists)
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
                "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
            )
        )


def _verify_vector_deps() -> None:
    """Verify vector-search dependencies at startup.

    - Development / test: log a loud warning and continue (TF-IDF fallback).
    - Production: fail fast — refuse to start with a misconfigured vector setup.
    """
    if not settings.VECTOR_SEARCH_ENABLED:
        return

    from app.database import get_database_url, is_sqlite_url

    db_url = get_database_url()
    is_prod = settings.APP_ENV == "production"

    if is_sqlite_url(db_url):
        try:
            import chromadb  # noqa: F401
        except ImportError:
            msg = (
                "VECTOR_SEARCH_ENABLED=true but chromadb is NOT installed.\n"
                "Install: pip install -r requirements-vector.txt"
            )
            if is_prod:
                raise RuntimeError(f"FATAL: {msg}")
            logger.critical(
                "╔══════════════════════════════════════════════════════════════╗\n"
                "║  VECTOR_SEARCH_ENABLED=true but chromadb is NOT installed.  ║\n"
                "║  Vector search will fall back to TF-IDF on every query.      ║\n"
                "║  Install: pip install -r requirements-vector.txt             ║\n"
                "╚══════════════════════════════════════════════════════════════╝"
            )

    # Also verify embedding provider is valid
    provider = settings.EMBEDDING_PROVIDER.lower()
    if provider == "local":
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            msg = (
                "EMBEDDING_PROVIDER=local but sentence-transformers is NOT installed.\n"
                "Install: pip install -r requirements-embedding-local.txt\n"
                "Or switch to API: EMBEDDING_PROVIDER=openai_compatible"
            )
            if is_prod:
                raise RuntimeError(f"FATAL: {msg}")
            logger.critical(
                "╔══════════════════════════════════════════════════════════════╗\n"
                "║  EMBEDDING_PROVIDER=local but sentence-transformers missing ║\n"
                "║  Embedding will fail at first query.                        ║\n"
                "║  Install: pip install -r requirements-embedding-local.txt   ║\n"
                "╚══════════════════════════════════════════════════════════════╝"
            )

    if provider == "openai_compatible":
        api_key = settings.EMBEDDING_API_KEY or settings.OPENAI_API_KEY
        base_url = settings.EMBEDDING_BASE_URL or settings.OPENAI_BASE_URL
        model_name = settings.EMBEDDING_MODEL_NAME

        missing = []
        if not api_key:
            missing.append("API Key (set EMBEDDING_API_KEY or OPENAI_API_KEY)")
        if not base_url:
            missing.append("Base URL (set EMBEDDING_BASE_URL or OPENAI_BASE_URL)")
        if not (model_name and model_name.strip()):
            missing.append("Model Name (set EMBEDDING_MODEL_NAME)")

        if missing:
            items = "\n  - ".join(missing)
            msg = (
                f"EMBEDDING_PROVIDER=openai_compatible but required config is missing:\n"
                f"  - {items}\n"
                f"Check your .env file."
            )
            if is_prod:
                raise RuntimeError(f"FATAL: {msg}")
            logger.critical(
                "╔══════════════════════════════════════════════════════════════╗\n"
                "║  EMBEDDING_PROVIDER=openai_compatible config incomplete:    ║\n"
                f"║  Missing: {items[:50]:<50s}║\n"
                "║  Check your .env file.                                      ║\n"
                "╚══════════════════════════════════════════════════════════════╝"
            )


def init_database() -> None:
    create_tables()
    upgrade_database()
    create_indexes()
    _migrate_pgvector()
    _verify_vector_deps()
