"""
Health check endpoint — includes DB + Redis status.
"""

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.database import check_db_health
from app.core.redis import redis_service

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health")
async def health_check():
    """Detailed health check including all dependencies."""
    db_health = await check_db_health()
    redis_health = await redis_service.health_check()

    all_healthy = (
        db_health.get("status") == "healthy"
        and redis_health.get("status") in ("healthy", "disconnected")
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "dependencies": {
            "database": db_health,
            "redis": redis_health,
        },
    }
