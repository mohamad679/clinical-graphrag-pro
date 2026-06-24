"""
Async SQLAlchemy engine, session management, and lifecycle helpers.
"""

from __future__ import annotations

import logging
import asyncio
import time
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory

from app.core.config import get_settings
from app.core.metrics import observe_db_query
from app.core.observability import export_trace_context

settings = get_settings()
logger = logging.getLogger(__name__)
REQUIRED_RUNTIME_TABLES = frozenset(
    {
        "audit_logs",
        "chat_messages",
        "chat_sessions",
        "documents",
        "image_annotations",
        "job_runs",
        "medical_images",
        "stored_assets",
        "users",
    }
)

db_url = settings.database_url
# Supabase transaction pooler requires prepared_statement_cache_size=0 for asyncpg
if "pooler.supabase.com" in db_url and "prepared_statement_cache_size=0" not in db_url:
    join_char = "&" if "?" in db_url else "?"
    db_url = f"{db_url}{join_char}prepared_statement_cache_size=0"

db_backend = make_url(db_url).get_backend_name()
engine_kwargs = {
    "echo": settings.debug,
}

if db_backend == "sqlite":
    engine_kwargs["connect_args"] = {
        "check_same_thread": False,
        "timeout": 30,
    }
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_async_engine(db_url, **engine_kwargs)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


@event.listens_for(engine.sync_engine, "connect")
def _configure_sqlite_connection(dbapi_connection, _connection_record):  # pragma: no cover - sync hook
    if db_backend != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception as e:
            logger.warning(
                "Failed to enable SQLite WAL mode, falling back to DELETE mode: %s",
                e,
            )
            try:
                cursor.execute("PRAGMA journal_mode=DELETE")
                cursor.execute("PRAGMA synchronous=FULL")
            except Exception:
                pass
    finally:
        cursor.close()


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # pragma: no cover - sync hook
    conn.info.setdefault("query_start_times", []).append(time.perf_counter())


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # pragma: no cover - sync hook
    start_stack = conn.info.get("query_start_times", [])
    started = start_stack.pop() if start_stack else None
    if started is None:
        return
    duration = max(time.perf_counter() - started, 0.0)
    normalized = statement.strip().split(None, 1)[0].upper() if statement else "UNKNOWN"
    observe_db_query(duration, statement_type=normalized)
    logger.info(
        "db.query.completed",
        extra={
            **export_trace_context(),
            "component": "db",
            "operation": "sql.query",
            "event": "db.query.completed",
            "statement_type": normalized,
            "duration_ms": round(duration * 1000, 2),
        },
    )


@event.listens_for(engine.sync_engine, "handle_error")
def _handle_db_error(exception_context):  # pragma: no cover - sync hook
    statement = exception_context.statement or ""
    normalized = statement.strip().split(None, 1)[0].upper() if statement else "UNKNOWN"
    logger.error(
        "db.query.failed",
        extra={
            **export_trace_context(),
            "component": "db",
            "operation": "sql.query",
            "event": "db.query.failed",
            "statement_type": normalized,
            "error_type": type(exception_context.original_exception).__name__,
            "error_message": str(exception_context.original_exception),
        },
    )


async def get_db():
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            # Only commit if there are pending modifications in the session to avoid locking on read-only queries.
            if session.new or session.dirty or session.deleted:
                await session.commit()
        except SQLAlchemyError as exc:
            logger.error(
                "db.session.failed",
                extra={
                    **export_trace_context(),
                    "component": "db",
                    "operation": "session.commit",
                    "event": "db.session.failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            await session.rollback()
            raise


async def check_db_health() -> dict:
    """Check database connectivity."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def create_tables():
    """Create all tables (for development only — use Alembic in production)."""
    import app.models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_missing_runtime_tables() -> list[str]:
    """Return required runtime tables that are absent from the connected database."""
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        existing_tables = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
    return sorted(REQUIRED_RUNTIME_TABLES - existing_tables)


async def ensure_runtime_schema(*, auto_repair: bool = False) -> dict:
    """Verify required runtime tables exist, repairing SQLite demo DBs when allowed."""
    missing = await get_missing_runtime_tables()
    if not missing:
        return {"status": "ready", "missing_tables": []}

    if auto_repair and db_backend == "sqlite":
        logger.warning(
            "SQLite runtime schema is missing tables; creating missing ORM tables: %s",
            ", ".join(missing),
        )
        await create_tables()
        remaining = await get_missing_runtime_tables()
        if not remaining:
            return {
                "status": "repaired",
                "missing_tables": [],
                "repaired_tables": missing,
            }
        missing = remaining

    raise RuntimeError(
        "Database schema is incomplete; missing required tables: "
        + ", ".join(missing)
    )


def get_alembic_config() -> Config:
    """Build an Alembic config using the current runtime database URL."""
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


async def check_migration_status() -> dict:
    """Check whether the current database revision matches Alembic head."""
    config = get_alembic_config()
    script = ScriptDirectory.from_config(config)
    head_revision = script.get_current_head()

    try:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            current_revision = result.scalar_one_or_none()
    except Exception as exc:
        return {
            "status": "uninitialized",
            "current_revision": None,
            "head_revision": head_revision,
            "error": str(exc),
        }

    return {
        "status": "current" if current_revision == head_revision else "outdated",
        "current_revision": current_revision,
        "head_revision": head_revision,
    }


async def run_migrations_to_head() -> dict:
    """Run Alembic migrations to the latest revision."""
    config = get_alembic_config()
    script = ScriptDirectory.from_config(config)
    head_revision = script.get_current_head()

    await asyncio.to_thread(command.upgrade, config, "head")

    return {
        "status": "current",
        "head_revision": head_revision,
    }
