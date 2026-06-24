"""
Clinical GraphRAG Pro — FastAPI Application
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.audit import AuditLogMiddleware
from app.core.config import get_settings
from app.core.database import check_migration_status, ensure_runtime_schema, run_migrations_to_head
from app.core.metrics import configure_metrics
from app.core.redis import redis_service
from app.core.logging_config import setup_logging, RequestLoggingMiddleware
from app.core.rate_limiter import RateLimitMiddleware
from app.api import chat, documents, graph, health, images, agents, eval, fine_tune, admin, audio, entity_normalization, evaluations
from app.worker import background_jobs_health

settings = get_settings()

setup_logging(json_output=not settings.debug, level=settings.log_level)
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
    worker_health = background_jobs_health()
    if worker_health["status"] != "healthy":
        log_fn = logger.error if settings.background_jobs_require_broker else logger.warning
        log_fn("Background jobs health: %s", worker_health)

    try:
        migration_status = await check_migration_status()
        if migration_status["status"] == "current":
            logger.info("📦 Database migrations are up to date")
        elif settings.auto_migrate_on_startup:
            logger.warning(
                "⚠️  Database migration status: %s (current=%s, head=%s); applying migrations",
                migration_status["status"],
                migration_status.get("current_revision"),
                migration_status.get("head_revision"),
            )
            await run_migrations_to_head()
            logger.info("📦 Database migrations applied")
        else:
            logger.warning(
                "⚠️  Database migration status: %s (current=%s, head=%s)",
                migration_status["status"],
                migration_status.get("current_revision"),
                migration_status.get("head_revision"),
            )
        schema_status = await ensure_runtime_schema(auto_repair=settings.auto_migrate_on_startup)
        if schema_status["status"] == "repaired":
            logger.warning(
                "📦 Database runtime schema repaired; created missing tables: %s",
                ", ".join(schema_status.get("repaired_tables", [])),
            )
    except Exception:
        logger.exception("Database migration check/apply failed")
        if settings.auto_migrate_on_startup:
            raise

    yield

    # Cleanup
    from app.services.audio_processing import audio_processing_service
    from app.services.llm import llm_service
    from app.services.neo4j_graph import neo4j_graph_service
    from app.services.vision import vision_service
    await audio_processing_service.close()
    await llm_service.close()
    await neo4j_graph_service.close()
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

allow_credentials = settings.cors_allow_credentials
if "*" in settings.cors_origins and allow_credentials:
    logger.warning("CORS wildcard origin cannot be used with credentials; disabling credentials.")
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# ── Production Middleware ────────────────────────────────

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuditLogMiddleware)

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
configure_metrics(app)


# ── Root ─────────────────────────────────────────────────

@app.get("/")
async def root():
    if settings.static_frontend_dir:
        index_path = settings.static_frontend_dir / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
        "metrics": "/metrics",
    }


if settings.static_frontend_dir:
    static_root = settings.static_frontend_dir.resolve()
    for asset_dir in ("css", "js"):
        asset_path = static_root / asset_dir
        if asset_path.is_dir():
            app.mount(f"/{asset_dir}", StaticFiles(directory=asset_path), name=f"frontend_{asset_dir}")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_fallback(full_path: str):
        if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "metrics")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (static_root / full_path).resolve()
        if static_root in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        index_path = static_root / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Frontend bundle not found")
