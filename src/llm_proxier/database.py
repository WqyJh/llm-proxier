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


async def init_db():
    async with engine.begin() as conn:
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

        await conn.run_sync(migrate)
