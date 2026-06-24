"""
Admin and authentication API endpoints.
"""

from __future__ import annotations

import logging
import platform
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.auth import auth_service, get_current_user, require_admin, require_authenticated_user, User
from app.core.config import get_settings
from app.core.database import get_db
from app.core.logging_config import request_metrics
from app.core.metrics import collect_operational_metrics_summary
from app.core.rate_limiter import rate_limiter
from app.models.audit_log import AuditLog
from app.models.chat import ChatSession
from app.models.user import User as DBUser
from app.services.privacy import export_user_data, purge_user_data
from app.services.vector_store import vector_store_service
from app.services.websocket_ticket import websocket_ticket_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Admin"])

_start_time = time.monotonic()


class LoginRequest(BaseModel):
    email: str
    password: str


class BootstrapAdminRequest(BaseModel):
    email: str
    password: str
    name: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class WebSocketTicketRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class WebSocketTicketResponse(BaseModel):
    ticket: str
    token_type: str
    expires_in: int
    expires_at: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    session_id: str
    user: dict[str, Any]


class BootstrapStatusResponse(BaseModel):
    bootstrap_open: bool
    user_count: int


class ForgotPasswordResponse(BaseModel):
    message: str
    reset_token: str | None = None


class AuditLogEntryResponse(BaseModel):
    id: str
    timestamp: datetime
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    request_ip: str | None
    session_id: str | None
    details: dict | None


class AuditLogListResponse(BaseModel):
    items: list[AuditLogEntryResponse]
    total: int
    page: int
    page_size: int


class AdminCreateUserRequest(BaseModel):
    email: str
    name: str
    role: str = "viewer"
    password: str | None = None
    is_active: bool = True


class AdminUpdateUserRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    password: str | None = None
    is_active: bool | None = None


def _request_ip(request: Request) -> str | None:
    return auth_service.request_ip(request)


def _request_user_agent(request: Request) -> str | None:
    return auth_service.request_user_agent(request)


def _login_response(payload: dict[str, Any]) -> LoginResponse:
    return LoginResponse(**payload)


@router.get("/auth/bootstrap/status", response_model=BootstrapStatusResponse)
async def bootstrap_status(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(func.count()).select_from(DBUser))
    user_count = int(result.scalar() or 0)
    return BootstrapStatusResponse(
        bootstrap_open=user_count == 0,
        user_count=user_count,
    )


@router.post("/auth/bootstrap", response_model=LoginResponse)
async def bootstrap_admin(
    request: BootstrapAdminRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    bootstrap_name = (request.name or get_settings().bootstrap_admin_name or "Administrator").strip() or "Administrator"
    db_user = await auth_service.bootstrap_admin_async(
        db,
        email=request.email,
        password=request.password,
        name=bootstrap_name,
    )
    result = await auth_service.authenticate_async(
        db,
        request.email,
        request.password,
        ip_address=_request_ip(http_request),
        user_agent=_request_user_agent(http_request),
    )
    if not result:
        raise HTTPException(status_code=500, detail="Bootstrap completed but automatic login failed")
    await write_audit_log(
        db,
        user_id=db_user.id,
        action="AUTH_BOOTSTRAP_ADMIN",
        resource_type="user",
        resource_id=db_user.id,
        request_ip=_request_ip(http_request),
        session_id=result.session_id,
        details={"email": db_user.email, "name": db_user.name, "role": db_user.role},
    )
    return _login_response(auth_service.tokens_payload(result))


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await auth_service.authenticate_async(
        db,
        request.email,
        request.password,
        ip_address=_request_ip(http_request),
        user_agent=_request_user_agent(http_request),
    )
    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return _login_response(auth_service.tokens_payload(result))


@router.post("/auth/refresh", response_model=LoginResponse)
async def refresh_token(
    request: RefreshRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await auth_service.refresh_tokens_async(
        db,
        request.refresh_token,
        ip_address=_request_ip(http_request),
        user_agent=_request_user_agent(http_request),
    )
    return _login_response(auth_service.tokens_payload(result))


@router.post("/auth/ws-ticket", response_model=WebSocketTicketResponse)
async def issue_websocket_ticket(
    request: WebSocketTicketRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    """Issue a short-lived, single-use WebSocket ticket bound to one chat session."""
    try:
        session_uuid = uuid.UUID(request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid session_id") from exc

    result = await db.execute(select(ChatSession).where(ChatSession.id == session_uuid))
    session = result.scalar_one_or_none()
    if session is None or (user.role != "admin" and session.user_id != user.id):
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        return WebSocketTicketResponse(
            **await websocket_ticket_service.issue_ticket(user, session_id=str(session_uuid))
        )
    except RuntimeError as exc:
        if str(exc) == "websocket_ticket_store_unavailable":
            raise HTTPException(status_code=503, detail="WebSocket ticket service is unavailable") from exc
        raise


@router.post("/auth/logout")
async def logout(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    await auth_service.logout_async(db, user)
    await write_audit_log(
        db,
        user_id=user.id,
        action="AUTH_LOGOUT",
        resource_type="auth",
        resource_id=user.session_id,
        request_ip=_request_ip(http_request),
        session_id=user.session_id,
        details={"scope": "current_session"},
    )
    return {"status": "logged_out", "session_id": user.session_id}


@router.post("/auth/logout-all")
async def logout_all(
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    revoked_count = await auth_service.logout_all_async(db, user)
    await write_audit_log(
        db,
        user_id=user.id,
        action="AUTH_LOGOUT_ALL",
        resource_type="auth",
        request_ip=_request_ip(http_request),
        session_id=user.session_id,
        details={"revoked_sessions": revoked_count},
    )
    return {"status": "logged_out_all", "revoked_sessions": revoked_count}


@router.post("/auth/change-password")
async def change_password(
    request: ChangePasswordRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    await auth_service.change_password_async(
        db,
        user=user,
        current_password=request.current_password,
        new_password=request.new_password,
    )
    await write_audit_log(
        db,
        user_id=user.id,
        action="AUTH_CHANGE_PASSWORD",
        resource_type="auth",
        request_ip=_request_ip(http_request),
        session_id=user.session_id,
        details={"revoked_sessions": "all"},
    )
    return {"status": "password_changed", "requires_reauthentication": True}


@router.post("/auth/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    reset_token = await auth_service.forgot_password_async(
        db,
        email=request.email,
        ip_address=_request_ip(http_request),
        user_agent=_request_user_agent(http_request),
    )
    response = {"message": "If that account exists, a password reset token has been issued."}
    if get_settings().debug and reset_token:
        response["reset_token"] = reset_token
    return ForgotPasswordResponse(**response)


@router.post("/auth/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    await auth_service.reset_password_async(
        db,
        reset_token=request.token,
        new_password=request.new_password,
    )
    await write_audit_log(
        db,
        user_id=None,
        action="AUTH_RESET_PASSWORD",
        resource_type="auth",
        request_ip=_request_ip(http_request),
        details={"token_prefix": request.token[:8]},
    )
    return {"status": "password_reset"}


@router.get("/auth/me")
async def get_me(user: User | None = Depends(get_current_user)):
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, **auth_service.user_payload(user)}


@router.get("/auth/sessions")
async def auth_sessions(
    include_revoked: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    sessions = await auth_service.list_sessions_async(
        db,
        requesting_user=user,
        include_revoked=include_revoked,
    )
    return {"sessions": sessions}


@router.post("/auth/sessions/{session_id}/revoke")
async def auth_revoke_session(
    session_id: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_authenticated_user),
):
    await auth_service.revoke_session_async(
        db,
        requesting_user=user,
        session_id=session_id,
    )
    await write_audit_log(
        db,
        user_id=user.id,
        action="AUTH_REVOKE_SESSION",
        resource_type="session",
        resource_id=session_id,
        request_ip=_request_ip(http_request),
        session_id=user.session_id,
    )
    return {"status": "session_revoked", "session_id": session_id}


@router.get("/admin/health")
async def admin_health(_user: User = Depends(require_admin)):
    uptime_seconds = time.monotonic() - _start_time
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
async def admin_metrics(_user: User = Depends(require_admin)):
    return {
        **request_metrics.get_summary(),
        "dashboard_metrics": await collect_operational_metrics_summary(),
    }


@router.get("/admin/sessions")
async def admin_sessions(
    target_user_id: str | None = None,
    include_revoked: bool = True,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    sessions = await auth_service.list_sessions_async(
        db,
        requesting_user=user,
        target_user_id=target_user_id,
        include_revoked=include_revoked,
    )
    return {"sessions": sessions}


@router.post("/admin/sessions/{session_id}/revoke")
async def admin_revoke_session(
    session_id: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    await auth_service.revoke_session_async(
        db,
        requesting_user=user,
        session_id=session_id,
    )
    await write_audit_log(
        db,
        user_id=user.id,
        action="ADMIN_REVOKE_SESSION",
        resource_type="session",
        resource_id=session_id,
        request_ip=_request_ip(http_request),
        session_id=user.session_id,
    )
    return {"status": "session_revoked", "session_id": session_id}


@router.get("/admin/config")
async def admin_config(_user: User = Depends(require_admin)):
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
        "auth": {
            "access_token_minutes": settings.jwt_expire_minutes,
            "refresh_token_days": settings.refresh_token_expire_days,
            "password_reset_minutes": settings.password_reset_token_expire_minutes,
        },
        "rate_limit": rate_limiter.get_stats(),
    }


@router.get("/admin/users")
async def admin_list_users(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_admin),
):
    return {"users": await auth_service.list_users_async(db)}


@router.post("/admin/users")
async def admin_create_user(
    request: AdminCreateUserRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    db_user, generated_password = await auth_service.create_user_async(
        db,
        email=request.email,
        name=request.name,
        role=request.role,
        password=request.password,
        is_active=request.is_active,
        created_by_user_id=user.id,
    )
    payload = auth_service.user_payload(auth_service._to_user_context(db_user)) | {"is_active": db_user.is_active}
    await write_audit_log(
        db,
        user_id=user.id,
        action="ADMIN_CREATE_USER",
        resource_type="user",
        resource_id=db_user.id,
        request_ip=_request_ip(http_request),
        session_id=user.session_id,
        details={"email": db_user.email, "role": db_user.role},
    )
    return {"user": payload, "generated_password": generated_password}


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: str,
    request: AdminUpdateUserRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    updated = await auth_service.update_user_async(
        db,
        user_id=user_id,
        acting_user_id=user.id,
        name=request.name,
        role=request.role,
        is_active=request.is_active,
        password=request.password,
    )
    payload = auth_service.user_payload(auth_service._to_user_context(updated)) | {"is_active": updated.is_active}
    await write_audit_log(
        db,
        user_id=user.id,
        action="ADMIN_UPDATE_USER",
        resource_type="user",
        resource_id=updated.id,
        request_ip=_request_ip(http_request),
        session_id=user.session_id,
        details={
            "name": request.name,
            "role": request.role,
            "is_active": request.is_active,
            "password_changed": request.password is not None,
        },
    )
    return {"user": payload}


@router.get("/admin/audit-log", response_model=AuditLogListResponse)
async def admin_audit_log(
    page: int = 1,
    page_size: int = 25,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 100)

    total_result = await db.execute(select(func.count(AuditLog.id)))
    total = total_result.scalar_one()

    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
    )
    items = result.scalars().all()

    return AuditLogListResponse(
        items=[
            AuditLogEntryResponse(
                id=str(item.id),
                timestamp=item.timestamp,
                user_id=item.user_id,
                action=item.action,
                resource_type=item.resource_type,
                resource_id=item.resource_id,
                request_ip=item.request_ip,
                session_id=item.session_id,
                details=item.details,
            )
            for item in items
        ],
        total=total,
        page=safe_page,
        page_size=safe_page_size,
    )


@router.post("/admin/gdpr/export/{user_id}")
async def admin_gdpr_export(
    user_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await export_user_data(db, user_id)


@router.delete("/admin/gdpr/purge/{user_id}")
async def admin_gdpr_purge(
    user_id: str,
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await purge_user_data(db, user_id)
    return {"status": "purged", "user_id": user_id, "deleted": result}


def _format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
