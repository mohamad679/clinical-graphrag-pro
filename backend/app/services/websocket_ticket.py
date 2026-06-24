"""
Short-lived, single-use WebSocket authentication tickets.

Redis is used when available. The in-memory store is intentionally limited to
non-production offline tests and local synthetic demos.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.auth import User
from app.core.config import get_settings
from app.core.redis import get_redis_client


@dataclass(frozen=True, slots=True)
class WebSocketTicketRecord:
    user_id: str
    tenant_id: str
    session_id: str | None
    expires_at_epoch: float
    issued_at_epoch: float


class WebSocketTicketService:
    def __init__(self) -> None:
        self._memory_store: dict[str, str] = {}
        self._memory_lock = asyncio.Lock()

    @staticmethod
    def hash_ticket(ticket: str) -> str:
        return hashlib.sha256(ticket.encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _key(ticket_hash: str) -> str:
        return f"ws_ticket:{ticket_hash}"

    @staticmethod
    def _now_epoch() -> float:
        return time.time()

    async def issue_ticket(self, user: User, *, session_id: str | None = None) -> dict[str, Any]:
        if not session_id:
            raise ValueError("session_id_required")
        settings = get_settings()
        raw_ticket = secrets.token_urlsafe(32)
        ticket_hash = self.hash_ticket(raw_ticket)
        now = self._now_epoch()
        record = WebSocketTicketRecord(
            user_id=user.id,
            tenant_id=user.tenant_id or user.id,
            session_id=session_id,
            issued_at_epoch=now,
            expires_at_epoch=now + settings.ws_ticket_ttl_seconds,
        )
        serialized = json.dumps(asdict(record), sort_keys=True)
        stored = await self._store(ticket_hash, serialized, ttl_seconds=settings.ws_ticket_ttl_seconds)
        if not stored:
            raise RuntimeError("websocket_ticket_store_unavailable")
        return {
            "ticket": raw_ticket,
            "token_type": "websocket_ticket",
            "expires_in": settings.ws_ticket_ttl_seconds,
            "expires_at": datetime.fromtimestamp(record.expires_at_epoch, tz=timezone.utc).isoformat(),
        }

    async def consume_ticket(
        self,
        ticket: str,
        *,
        expected_session_id: str | None = None,
    ) -> WebSocketTicketRecord | None:
        if not ticket or len(ticket) > 256:
            return None
        ticket_hash = self.hash_ticket(ticket)
        raw = await self._consume(ticket_hash)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            record = WebSocketTicketRecord(
                user_id=str(payload["user_id"]),
                tenant_id=str(payload["tenant_id"]),
                session_id=payload.get("session_id"),
                expires_at_epoch=float(payload["expires_at_epoch"]),
                issued_at_epoch=float(payload["issued_at_epoch"]),
            )
        except Exception:
            return None

        if record.expires_at_epoch <= self._now_epoch():
            return None
        if not record.session_id:
            return None
        if expected_session_id and str(record.session_id) != str(expected_session_id):
            return None
        return record

    async def _store(self, ticket_hash: str, serialized: str, *, ttl_seconds: int) -> bool:
        try:
            client = await get_redis_client()
        except Exception:
            return await self._store_memory(ticket_hash, serialized)
        return bool(await client.set(self._key(ticket_hash), serialized, ex=ttl_seconds, nx=True))

    async def _consume(self, ticket_hash: str) -> str | None:
        try:
            client = await get_redis_client()
        except Exception:
            return await self._consume_memory(ticket_hash)

        script = """
        local value = redis.call('GET', KEYS[1])
        if value then
          redis.call('DEL', KEYS[1])
        end
        return value
        """
        value = await client.eval(script, 1, self._key(ticket_hash))
        return str(value) if value else None

    async def _store_memory(self, ticket_hash: str, serialized: str) -> bool:
        settings = get_settings()
        if settings.app_env == "production" or not settings.ws_ticket_allow_memory_fallback:
            return False
        async with self._memory_lock:
            self._memory_store[self._key(ticket_hash)] = serialized
        return True

    async def _consume_memory(self, ticket_hash: str) -> str | None:
        settings = get_settings()
        if settings.app_env == "production" or not settings.ws_ticket_allow_memory_fallback:
            return None
        async with self._memory_lock:
            return self._memory_store.pop(self._key(ticket_hash), None)


websocket_ticket_service = WebSocketTicketService()
