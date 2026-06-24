"""
Health and diagnostics endpoints.
"""

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import check_db_health, check_migration_status
from app.core.metrics import refresh_worker_queue_depths
from app.core.redis import redis_service
from app.services.llm import llm_service
from app.services.neo4j_graph import check_neo4j_health
from app.services.vector_store import vector_store_service
from app.worker import background_jobs_health

router = APIRouter(tags=["Health"])
settings = get_settings()


def _aggregate_health(services: dict) -> str:
    states = [payload.get("status", "unknown") for payload in services.values()]
    allowed_healthy = {"healthy", "disabled", "not_configured"}
    if settings.app_env != "production":
        allowed_healthy.add("disconnected")
        allowed_healthy.add("degraded")
    if all(state in allowed_healthy for state in states):
        return "healthy"
    if settings.app_env == "production" and any(state in {"unhealthy", "disconnected"} for state in states):
        return "unhealthy"
    if any(state in {"healthy", "degraded"} for state in states):
        return "degraded"
    return "unhealthy"


@router.get("/health")
async def health_check():
    """Basic liveness endpoint."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/health/detailed")
async def detailed_health_check():
    """Check backing services used by production deployments."""
    db_health = await check_db_health()
    migration_status = await check_migration_status()
    migration_health = {
        **migration_status,
        "status": "healthy" if migration_status.get("status") == "current" else "unhealthy",
    }
    redis_health = await redis_service.health_check()
    neo4j_health = await check_neo4j_health()
    llm_health = await llm_service.health_check(timeout_seconds=5.0)
    vector_stats = vector_store_service.get_stats()
    vector_health = {
        "status": "healthy" if not vector_stats.get("error") else "unhealthy",
        **vector_stats,
    }
    worker_health = background_jobs_health()
    queue_depths = await refresh_worker_queue_depths()
    worker_health["queue_depth"] = queue_depths

    services = {
        "postgres": db_health,
        "migrations": migration_health,
        "redis": redis_health,
        "neo4j": neo4j_health,
        "vector_store": vector_health,
        "llm_provider": llm_health,
        "background_jobs": worker_health,
    }

    return {
        "status": _aggregate_health(services),
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "services": services,
    }


@router.get("/health/disclaimer")
async def health_disclaimer():
    """Expose the clinical safety disclaimer used in the UI."""
    return {"disclaimer": settings.disclaimer_text}
