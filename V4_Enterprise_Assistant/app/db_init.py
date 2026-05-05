from sqlalchemy import inspect, text

from app.database import Base, engine
# 确保所有 SQLAlchemy 模型被导入并注册到 Base.metadata
from app import models


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def column_exists(table_name: str, column_name: str) -> bool:
    inspector = inspect(engine)
    return any(
        column["name"] == column_name
        for column in inspector.get_columns(table_name)
    )


def upgrade_database() -> None:
    if column_exists("customers", "cooperation_status"):
        return

    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE customers ADD COLUMN cooperation_status VARCHAR(20)")
        )


def create_indexes() -> None:
    """为已有 SQLite 数据库幂等补建索引。"""
    with engine.begin() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_followups_customer_id ON followups (customer_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_document_chunks_filename ON document_chunks (filename)")
        )


def init_database() -> None:
    create_tables()
    upgrade_database()
    create_indexes()
