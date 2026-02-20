"""
Async SQLAlchemy engine, session management, and lifecycle helpers.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.core.config import get_settings

settings = get_settings()

db_url = settings.database_url
# Supabase transaction pooler requires prepared_statement_cache_size=0 for asyncpg
if "pooler.supabase.com" in db_url and "prepared_statement_cache_size=0" not in db_url:
    join_char = "&" if "?" in db_url else "?"
    db_url = f"{db_url}{join_char}prepared_statement_cache_size=0"

engine = create_async_engine(
    db_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db():
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
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
    from app.models import Document, ChatSession, ChatMessage  # noqa: F401
    from app.models import Workflow, WorkflowStep, ToolCall  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
