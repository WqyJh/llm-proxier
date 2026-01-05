import datetime
from collections.abc import AsyncGenerator

from sqlalchemy import JSON, DateTime, Text, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from llm_proxier.config import settings

# 配置连接池参数以提高稳定性和性能
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    # 连接池配置
    pool_size=10,  # 连接池大小
    max_overflow=20,  # 最大溢出连接
    pool_timeout=30,  # 获取连接超时时间(秒)
    pool_recycle=3600,  # 连接回收时间(秒)
    pool_pre_ping=True,  # 预检查连接有效性
    # SQLite 特定配置
    connect_args={
        "check_same_thread": False,  # 允许跨线程使用连接
        "timeout": 30,  # 查询超时
    }
    if "sqlite" in settings.DATABASE_URL
    else {},
)

async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    method: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)

    # We store headers/body as JSON or Text.
    # Request body can be large.
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_body: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Response might be stream, stored as aggregated string
    status_code: Mapped[int | None] = mapped_column()
    fail: Mapped[int] = mapped_column(default=0)

    # Create an index on timestamp descending for efficient pagination
    # and newest-first queries. We use raw SQL in migration to ensure
    # compatibility across SQLite/Postgres.
    __table_args__ = ()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def init_db(test_engine=None):
    """Initialize database with schema, migrations, and FTS5 full-text search.

    This function performs the following operations:

    1. Creates database tables based on SQLAlchemy models
    2. Runs idempotent migrations (adds missing columns)
    3. Creates indexes for performance optimization
    4. Sets up FTS5 virtual table for full-text search
    5. Creates triggers to auto-sync FTS index with main table

    FTS5 Architecture:
    - request_logs: Main table storing log data
    - request_logs_fts: Virtual table storing search index (created automatically)
    - Triggers: Automatically maintain sync between main table and FTS index

    Searchable fields: request_body, response_body, path, method

    The FTS5 implementation uses:
    - unicode61 tokenizer: Supports Chinese and Unicode text
    - External content: References main table to avoid data duplication
    - Automatic triggers: INSERT, UPDATE, DELETE operations

    See docs/design/fts.md for detailed design documentation.

    Args:
        test_engine: Optional engine for testing. If provided, uses this instead of global engine.
    """
    use_engine = test_engine if test_engine is not None else engine
    async with use_engine.begin() as conn:
        # Create tables if they don't exist
        await conn.run_sync(Base.metadata.create_all)

        # Simple, idempotent column-level migrations
        def migrate(sync_conn):
            inspector = inspect(sync_conn)
            existing_columns = {col["name"] for col in inspector.get_columns("request_logs")}

            # Add "fail" column if missing
            if "fail" not in existing_columns:
                dialect = sync_conn.dialect.name

                if dialect == "sqlite":
                    # SQLite: add column, then backfill existing rows
                    sync_conn.execute(text("ALTER TABLE request_logs ADD COLUMN fail INTEGER"))
                    sync_conn.execute(text("UPDATE request_logs SET fail = 0 WHERE fail IS NULL"))
                else:
                    # Generic SQL for most other dialects
                    sync_conn.execute(text("ALTER TABLE request_logs ADD COLUMN fail INTEGER DEFAULT 0"))
                    sync_conn.execute(text("UPDATE request_logs SET fail = 0 WHERE fail IS NULL"))

            # Ensure descending timestamp index exists
            # Use IF NOT EXISTS for SQLite >= 3.9 and Postgres
            sync_conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_request_logs_timestamp_desc ON request_logs(timestamp DESC)")
            )

            # Additional composite index for pagination queries (timestamp + id for stable ordering)
            sync_conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_request_logs_timestamp_id_desc ON request_logs(timestamp DESC, id DESC)"
                )
            )

            # Index for count queries (covering index)
            sync_conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_request_logs_covering ON request_logs(timestamp DESC, id, method, path, status_code, fail, request_body, response_body)"
                )
            )

            # FTS5 Full-Text Search setup
            # Check if FTS5 virtual table exists
            try:
                sync_conn.execute(text("SELECT 1 FROM request_logs_fts LIMIT 1"))
                fts_exists = True
            except Exception:
                fts_exists = False

            if not fts_exists:
                # Create FTS5 virtual table
                # Using unicode61 tokenizer for Chinese support
                sync_conn.execute(
                    text(
                        """
                    CREATE VIRTUAL TABLE IF NOT EXISTS request_logs_fts USING fts5(
                        request_body,
                        response_body,
                        path,
                        method,
                        content='request_logs',
                        content_rowid='id',
                        tokenize='unicode61'
                    )
                """
                    )
                )

                # Create triggers to keep FTS index in sync with main table
                # After INSERT
                sync_conn.execute(
                    text(
                        """
                    CREATE TRIGGER IF NOT EXISTS request_logs_ai AFTER INSERT ON request_logs BEGIN
                        INSERT INTO request_logs_fts(rowid, request_body, response_body, path, method)
                        VALUES (new.id, new.request_body, new.response_body, new.path, new.method);
                    END;
                """
                    )
                )

                # After UPDATE
                sync_conn.execute(
                    text(
                        """
                    CREATE TRIGGER IF NOT EXISTS request_logs_au AFTER UPDATE ON request_logs BEGIN
                        DELETE FROM request_logs_fts WHERE rowid=old.id;
                        INSERT INTO request_logs_fts(rowid, request_body, response_body, path, method)
                        VALUES (new.id, new.request_body, new.response_body, new.path, new.method);
                    END;
                """
                    )
                )

                # After DELETE
                # Note: FTS5 with external content has a known issue where internal
                # tables (_docsize, _idx) don't get cleaned up properly on DELETE.
                # We call 'rebuild' to clean up orphaned entries and keep the index consistent.
                # See: https://www.sqlite.org/fts5.html#external_content_tables
                sync_conn.execute(
                    text(
                        """
                    CREATE TRIGGER IF NOT EXISTS request_logs_ad AFTER DELETE ON request_logs BEGIN
                        DELETE FROM request_logs_fts WHERE rowid=old.id;
                        -- Rebuild to clean up orphaned internal entries
                        INSERT INTO request_logs_fts(request_logs_fts) VALUES('rebuild');
                    END;
                """
                    )
                )

                # Populate existing data into FTS index
                sync_conn.execute(
                    text(
                        """
                    INSERT INTO request_logs_fts(rowid, request_body, response_body, path, method)
                    SELECT id, request_body, response_body, path, method FROM request_logs
                    WHERE id NOT IN (SELECT rowid FROM request_logs_fts)
                """
                    )
                )

        await conn.run_sync(migrate)
