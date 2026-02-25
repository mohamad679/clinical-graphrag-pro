"""
Clinical GraphRAG Pro — FastAPI Application
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.redis import redis_service
from app.core.logging_config import setup_logging, RequestLoggingMiddleware
from app.core.rate_limiter import RateLimitMiddleware
from app.api import chat, documents, graph, health, images, agents, eval, fine_tune, admin, audio, entity_normalization, evaluations

settings = get_settings()

setup_logging(json_output=not settings.debug)
logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle events."""
    logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version}")

    # Create upload directory
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    # Connect Redis (gracefully — app works without it)
    await redis_service.connect()

    # Create tables if they don't exist (dev convenience)
    if settings.debug:
        from app.core.database import create_tables
        try:
            await create_tables()
            logger.info("📦 Database tables ensured")
        except Exception as e:
            logger.warning(f"⚠️  Could not create tables: {e}")

    yield

    # Cleanup
    from app.services.llm import llm_service
    from app.services.vision import vision_service
    await llm_service.close()
    await vision_service.close()
    await redis_service.close()
    logger.info("👋 Shut down complete.")


# ── Application ──────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Enterprise Clinical AI Platform powered by GraphRAG",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Production Middleware ────────────────────────────────

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# ── Routers ──────────────────────────────────────────────

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(documents.router, prefix=settings.api_prefix)
app.include_router(graph.router, prefix=settings.api_prefix)
app.include_router(images.router, prefix=settings.api_prefix)
app.include_router(agents.router, prefix=settings.api_prefix)
app.include_router(eval.router, prefix=settings.api_prefix)
app.include_router(fine_tune.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(audio.router, prefix=settings.api_prefix)
app.include_router(entity_normalization.router, prefix=settings.api_prefix)
app.include_router(evaluations.router, prefix=settings.api_prefix)


# ── Root ─────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }
