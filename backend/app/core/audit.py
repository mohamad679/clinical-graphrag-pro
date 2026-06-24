"""
Audit logging middleware for API requests.
"""

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.auth import auth_service
from app.core.database import async_session_factory
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def write_audit_log(
    session,
    *,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    request_ip: str | None = None,
    session_id: str | None = None,
    details: dict[str, Any] | None = None,
    notes: str | None = None,
) -> None:
    """Persist an audit log entry with the caller's transaction."""
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_ip=request_ip,
            session_id=session_id,
            details=details or {},
            notes=notes,
        )
    )
    await session.flush()


def _extract_token_payload(request: Request) -> dict[str, Any] | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        return auth_service.verify_token(token)
    except Exception:
        return None


def _derive_audit_fields(request: Request, status_code: int) -> tuple[str, str, str | None]:
    path = request.url.path
    method = request.method.upper()
    parts = [part for part in path.split("/") if part]

    resource_type = parts[1] if len(parts) > 1 else "system"
    resource_id = None
    if len(parts) > 2 and parts[2] not in {"upload", "search", "status", "analyze", "files", "thumbnails"}:
        resource_id = parts[2]

    if path == "/api/auth/login":
        return ("AUTH_LOGIN" if status_code < 400 else "AUTH_FAIL", "auth", None)
    if path == "/api/chat" and method == "POST":
        return ("CHAT_QUERY", "chat", None)
    if path == "/api/documents/upload" and method == "POST":
        return ("DOCUMENT_UPLOAD", "document", None)
    if path.startswith("/api/documents/") and method == "DELETE":
        return ("DOCUMENT_DELETE", "document", resource_id)
    if path == "/api/images/upload" and method == "POST":
        return ("IMAGE_UPLOAD", "image", None)
    if path.startswith("/api/images/") and path.endswith("/analyze") and method == "POST":
        return ("IMAGE_ANALYZE", "image", resource_id)
    if path.startswith("/api/agents") and method == "POST":
        return ("AGENT_RUN", "agent", resource_id)
    return (f"{method}_{resource_type}".upper(), resource_type, resource_id)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Persist one audit record per API request."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        payload = _extract_token_payload(request)
        user_id = payload.get("sub") if payload else None
        session_id = (payload.get("sid") or payload.get("jti")) if payload else None
        request_ip = request.client.host if request.client else None

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            status_code = 500
            await self._write_audit_log(
                request=request,
                status_code=status_code,
                user_id=user_id,
                session_id=session_id,
                request_ip=request_ip,
                error=str(exc),
            )
            raise

        await self._write_audit_log(
            request=request,
            status_code=status_code,
            user_id=user_id,
            session_id=session_id,
            request_ip=request_ip,
        )
        return response

    async def _write_audit_log(
        self,
        request: Request,
        status_code: int,
        user_id: str | None,
        session_id: str | None,
        request_ip: str | None,
        error: str | None = None,
    ) -> None:
        action, resource_type, resource_id = _derive_audit_fields(request, status_code)
        details: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.query_params),
            "status_code": status_code,
        }
        if error:
            details["error"] = error

        try:
            async with async_session_factory() as session:
                await write_audit_log(
                    session,
                    user_id=user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    request_ip=request_ip,
                    session_id=session_id,
                    details=details,
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to persist audit log: %s", exc)
