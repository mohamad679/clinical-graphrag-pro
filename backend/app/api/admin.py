"""
Admin & Auth API endpoints.
Login, health dashboard, metrics, and session management.
"""

import logging
import platform
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import auth_service, get_current_user, require_admin, User
from app.core.rate_limiter import rate_limiter
from app.core.logging_config import request_metrics
from app.services.vector_store import vector_store_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin"])

_start_time = time.monotonic()


# ── Schemas ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: dict


# ── Auth Endpoints ───────────────────────────────────────

@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    result = auth_service.authenticate(request.email, request.password)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user, token = result

    # Record session
    import jwt as pyjwt
    payload = pyjwt.decode(token, options={"verify_signature": False})
    auth_service.record_session(user, payload.get("jti", ""))

    return LoginResponse(
        token=token,
        user={
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
        },
    )


@router.get("/auth/me")
async def get_me(user: User | None = Depends(get_current_user)):
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
    }


# ── Admin Endpoints ─────────────────────────────────────

@router.get("/admin/health")
async def admin_health():
    """Detailed system health for dashboard."""
    uptime_seconds = time.monotonic() - _start_time

    # Vector store stats
    vs_stats = vector_store_service.get_stats()

    return {
        "status": "healthy",
        "uptime_seconds": round(uptime_seconds, 1),
        "uptime_human": _format_uptime(uptime_seconds),
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "vector_store": {
                "status": "up",
                "total_chunks": vs_stats.get("total_chunks", 0),
                "total_documents": vs_stats.get("total_documents", 0),
            },
            "llm": {"status": "up"},
            "rate_limiter": rate_limiter.get_stats(),
        },
    }


@router.get("/admin/metrics")
async def admin_metrics():
    """Request metrics for dashboard charts."""
    return request_metrics.get_summary()


@router.get("/admin/sessions")
async def admin_sessions():
    """Active sessions list."""
    return {"sessions": auth_service.get_sessions()}


@router.get("/admin/config")
async def admin_config():
    """Non-sensitive configuration display."""
    from app.core.config import get_settings
    settings = get_settings()

    return {
        "llm": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
        },
        "embedding": {
            "model": settings.embedding_model,
            "dimension": settings.embedding_dim,
        },
        "rag": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "top_k": settings.top_k,
            "use_hybrid_search": settings.use_hybrid_search,
            "use_reranking": settings.use_reranking,
        },
        "fine_tune": {
            "base_model": settings.fine_tune_base_model,
            "lora_rank": settings.lora_rank,
        },
        "rate_limit": rate_limiter.get_stats(),
    }


def _format_uptime(seconds: float) -> str:
    """Format uptime as human-readable string."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
