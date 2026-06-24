"""
JWT authentication with persistent users, sessions, refresh tokens, and password reset flows.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session_factory, get_db
from app.models.user import (
    LoginAttempt,
    PasswordResetToken,
    RefreshToken,
    User as DBUser,
    UserSession,
)
from app.core.metrics import record_auth_legacy_hash_upgrade

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

ROLE_RANK = {
    "viewer": 10,
    "nurse": 20,
    "physician": 30,
    "admin": 40,
}
PASSWORD_MIN_LENGTH = 8
ACCESS_TOKEN_TYPE = "access"
LOCAL_UI_USER_ID = "local-ui"
ARGON2_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
ARGON2_SCHEME = "argon2id"
SHA256_MIGRATION_DEADLINE = "2026-09-30"


@dataclass(slots=True)
class User:
    """Authenticated user context returned to API handlers."""

    id: str
    email: str
    name: str
    role: str
    created_at: str
    tenant_id: str | None = None
    session_id: str | None = None
    is_verified: bool = False
    must_change_password: bool = False


@dataclass(slots=True)
class AuthTokens:
    """Access/refresh token bundle returned by login and refresh flows."""

    user: User
    access_token: str
    refresh_token: str
    token_type: str
    session_id: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    refresh_token_id: str

    @property
    def expires_in(self) -> int:
        remaining = int((self.access_expires_at - datetime.now(timezone.utc)).total_seconds())
        return max(remaining, 0)


@dataclass(slots=True)
class PasswordVerification:
    valid: bool
    scheme: str | None
    needs_rehash: bool = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _local_development_user() -> User:
    return User(
        id=LOCAL_UI_USER_ID,
        email="local-ui@clinical.local",
        name="Local UI Mode",
        role="admin",
        created_at=_utcnow().isoformat(),
        tenant_id=LOCAL_UI_USER_ID,
        session_id=LOCAL_UI_USER_ID,
        is_verified=True,
        must_change_password=False,
    )


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _build_session_query() -> Select[tuple[UserSession, DBUser]]:
    return select(UserSession, DBUser).join(DBUser, DBUser.id == UserSession.user_id)


class AuthService:
    """Database-backed authentication service."""

    def __init__(self):
        settings = get_settings()
        self._secret = settings.jwt_secret
        self._algorithm = "HS256"
        self._access_expire_minutes = settings.jwt_expire_minutes
        self._refresh_expire_days = settings.refresh_token_expire_days
        self._password_reset_expire_minutes = settings.password_reset_token_expire_minutes

    # ── Password Hashing ─────────────────────────────────

    @staticmethod
    def _hash_password(password: str) -> str:
        return ARGON2_HASHER.hash(password)

    @staticmethod
    def _hash_password_pbkdf2_for_migration_tests(password: str) -> str:
        iterations = 120000
        salt = secrets.token_bytes(16)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return (
            f"pbkdf2_sha256${iterations}$"
            f"{base64.b64encode(salt).decode()}$"
            f"{base64.b64encode(derived).decode()}"
        )

    def _verify_password(self, plain: str, hashed: str) -> bool:
        return self._verify_password_with_metadata(plain, hashed).valid

    def _verify_password_with_metadata(self, plain: str, hashed: str) -> PasswordVerification:
        if not hashed:
            return PasswordVerification(False, None)
        if hashed.startswith("$argon2id$"):
            try:
                valid = ARGON2_HASHER.verify(hashed, plain)
                return PasswordVerification(
                    bool(valid),
                    ARGON2_SCHEME,
                    bool(valid and ARGON2_HASHER.check_needs_rehash(hashed)),
                )
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return PasswordVerification(False, ARGON2_SCHEME)
        if hashed.startswith("pbkdf2_sha256$"):
            try:
                _, iter_text, salt_text, hash_text = hashed.split("$", 3)
                iterations = int(iter_text)
                salt = base64.b64decode(salt_text.encode())
                expected = base64.b64decode(hash_text.encode())
                actual = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, iterations)
                valid = hmac.compare_digest(actual, expected)
                return PasswordVerification(valid, "pbkdf2_sha256", needs_rehash=valid)
            except Exception:
                return PasswordVerification(False, "pbkdf2_sha256")
        # Temporary migration-only support for pre-PBKDF2 SHA-256 password
        # hashes. Do not create new SHA-256 hashes. Remove after
        # SHA256_MIGRATION_DEADLINE once all persisted users have logged in or
        # been administratively reset.
        valid = hmac.compare_digest(hashlib.sha256(plain.encode()).hexdigest(), hashed)
        return PasswordVerification(valid, "sha256_legacy", needs_rehash=valid)

    @staticmethod
    def _validate_password_strength(password: str) -> None:
        if len(password) < PASSWORD_MIN_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.",
            )

    @staticmethod
    def _hash_opaque_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _generate_opaque_token(prefix: str) -> str:
        return f"{prefix}_{secrets.token_urlsafe(48)}"

    # ── Token Helpers ────────────────────────────────────

    def _access_expiry(self) -> datetime:
        return _utcnow() + timedelta(minutes=self._access_expire_minutes)

    def _refresh_expiry(self) -> datetime:
        return _utcnow() + timedelta(days=self._refresh_expire_days)

    def _password_reset_expiry(self) -> datetime:
        return _utcnow() + timedelta(minutes=self._password_reset_expire_minutes)

    def create_access_token(self, user: User, session_id: str) -> tuple[str, str, datetime]:
        issued_at = _utcnow()
        expires_at = issued_at + timedelta(minutes=self._access_expire_minutes)
        jti = _uuid_str()
        payload = {
            "sub": user.id,
            "sid": session_id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "type": ACCESS_TOKEN_TYPE,
            "exp": expires_at,
            "iat": issued_at,
            "jti": jti,
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return token, jti, expires_at

    def verify_token(self, token: str, *, expected_type: str | None = ACCESS_TOKEN_TYPE) -> dict[str, Any]:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            ) from exc

        token_type = payload.get("type")
        if expected_type and token_type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        return payload

    # ── Public Serialization ─────────────────────────────

    @staticmethod
    def _to_user_context(db_user: DBUser, *, session_id: str | None = None) -> User:
        return User(
            id=db_user.id,
            email=db_user.email,
            name=db_user.name,
            role=db_user.role,
            created_at=db_user.created_at.isoformat(),
            tenant_id=getattr(db_user, "tenant_id", None) or db_user.id,
            session_id=session_id,
            is_verified=db_user.is_verified,
            must_change_password=db_user.must_change_password,
        )

    @staticmethod
    def user_payload(user: User) -> dict[str, Any]:
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "created_at": user.created_at,
            "is_verified": user.is_verified,
            "must_change_password": user.must_change_password,
            "session_id": user.session_id,
        }

    @staticmethod
    def tokens_payload(bundle: AuthTokens) -> dict[str, Any]:
        return {
            "access_token": bundle.access_token,
            "refresh_token": bundle.refresh_token,
            "token_type": bundle.token_type,
            "expires_in": bundle.expires_in,
            "session_id": bundle.session_id,
            "user": AuthService.user_payload(bundle.user),
        }

    @staticmethod
    def session_payload(session: UserSession, db_user: DBUser) -> dict[str, Any]:
        created_at = _as_utc(session.created_at)
        updated_at = _as_utc(session.updated_at)
        last_seen_at = _as_utc(session.last_seen_at)
        expires_at = _as_utc(session.expires_at)
        access_expires_at = _as_utc(session.access_expires_at)
        revoked_at = _as_utc(session.revoked_at)
        return {
            "id": session.id,
            "user_id": session.user_id,
            "user_email": db_user.email,
            "user_name": db_user.name,
            "user_role": db_user.role,
            "user_agent": session.user_agent,
            "ip_address": session.ip_address,
            "created_at": created_at.isoformat() if created_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
            "last_seen_at": last_seen_at.isoformat() if last_seen_at else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "access_expires_at": access_expires_at.isoformat() if access_expires_at else None,
            "revoked_at": revoked_at.isoformat() if revoked_at else None,
            "revoke_reason": session.revoke_reason,
            "is_active": revoked_at is None and bool(expires_at and expires_at > _utcnow()),
        }

    # ── Request Metadata ─────────────────────────────────

    @staticmethod
    def request_ip(request: Request | None) -> str | None:
        if not request:
            return None
        return request.client.host if request.client else None

    @staticmethod
    def request_user_agent(request: Request | None) -> str | None:
        if not request:
            return None
        return request.headers.get("user-agent")

    # ── Core Queries ─────────────────────────────────────

    async def _get_user_by_email(self, db: AsyncSession, email: str) -> DBUser | None:
        normalized = _normalize_email(email)
        result = await db.execute(select(DBUser).where(DBUser.email == normalized))
        return result.scalar_one_or_none()

    async def _get_user_record_by_id(self, db: AsyncSession, user_id: str) -> DBUser | None:
        result = await db.execute(select(DBUser).where(DBUser.id == user_id))
        return result.scalar_one_or_none()

    async def _check_brute_force(
        self, db: AsyncSession, *, email: str, ip_address: str | None
    ) -> None:
        cutoff = _utcnow() - timedelta(minutes=15)
        filters = [LoginAttempt.email == _normalize_email(email)]
        if ip_address:
            filters.append(LoginAttempt.ip_address == ip_address)

        identity_filter = filters[0] if len(filters) == 1 else or_(*filters)
        result = await db.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.attempted_at >= cutoff,
                identity_filter,
            )
        )
        failed_count = int(result.scalar() or 0)
        if failed_count >= 5:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Try again in 15 minutes.",
            )

    async def _record_login_attempt(
        self,
        db: AsyncSession,
        *,
        email: str,
        user_id: str | None,
        ip_address: str | None,
        user_agent: str | None,
        succeeded: bool,
        failure_reason: str | None = None,
    ) -> None:
        db.add(
            LoginAttempt(
                email=_normalize_email(email),
                user_id=user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                succeeded=succeeded,
                failure_reason=failure_reason,
            )
        )

    async def _issue_session_tokens(
        self,
        db: AsyncSession,
        db_user: DBUser,
        *,
        ip_address: str | None,
        user_agent: str | None,
        session: UserSession | None = None,
    ) -> AuthTokens:
        refresh_expires_at = self._refresh_expiry()

        if session is None:
            session = UserSession(
                id=_uuid_str(),
                user_id=db_user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_at=refresh_expires_at,
            )
            db.add(session)
        else:
            session.ip_address = ip_address or session.ip_address
            session.user_agent = user_agent or session.user_agent
            session.expires_at = refresh_expires_at
            session.revoked_at = None
            session.revoke_reason = None
            session.last_seen_at = _utcnow()

        user_context = self._to_user_context(db_user, session_id=session.id)
        user_context.session_id = session.id
        access_token, access_jti, access_expires_at = self.create_access_token(user_context, session.id)
        refresh_token = self._generate_opaque_token("rt")
        refresh_record = RefreshToken(
            id=_uuid_str(),
            user_id=db_user.id,
            session_id=session.id,
            token_hash=self._hash_opaque_token(refresh_token),
            expires_at=refresh_expires_at,
        )
        db.add(refresh_record)

        session.current_access_jti = access_jti
        session.access_expires_at = access_expires_at
        session.current_refresh_token_id = refresh_record.id
        session.last_seen_at = _utcnow()
        session.expires_at = refresh_expires_at

        return AuthTokens(
            user=user_context,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            session_id=session.id,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            refresh_token_id=refresh_record.id,
        )

    async def _revoke_session(self, db: AsyncSession, session: UserSession, reason: str) -> None:
        now = _utcnow()
        session.revoked_at = session.revoked_at or now
        session.revoke_reason = reason
        session.current_access_jti = None
        session.access_expires_at = now
        session.current_refresh_token_id = None
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.session_id == session.id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        for token in result.scalars():
            token.revoked_at = now
            if not token.revoke_reason:
                token.revoke_reason = reason

    async def _ensure_active_session(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        user_id: str,
    ) -> tuple[UserSession, DBUser]:
        result = await db.execute(
            _build_session_query().where(UserSession.id == session_id, UserSession.user_id == user_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found")

        session, db_user = row
        if not db_user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account is inactive")
        if session.revoked_at is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")
        session_expires_at = _as_utc(session.expires_at)
        if session_expires_at and session_expires_at <= _utcnow():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has expired")
        return session, db_user

    # ── Authentication Flows ─────────────────────────────

    async def authenticate_async(
        self,
        db: AsyncSession,
        email: str,
        password: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthTokens | None:
        normalized_email = _normalize_email(email)
        await self._check_brute_force(db, email=normalized_email, ip_address=ip_address)
        db_user = await self._get_user_by_email(db, normalized_email)
        failure_reason: str | None = None
        settings = get_settings()

        if not db_user:
            failure_reason = "user_not_found"
        elif not db_user.is_active:
            failure_reason = "user_inactive"
        elif settings.require_email_verification and not db_user.is_verified:
            failure_reason = "email_not_verified"
        verification = PasswordVerification(False, None)
        if db_user and db_user.is_active and not (settings.require_email_verification and not db_user.is_verified):
            verification = self._verify_password_with_metadata(password, db_user.password_hash)
            if not verification.valid:
                failure_reason = "invalid_password"

        if failure_reason:
            await self._record_login_attempt(
                db,
                email=normalized_email,
                user_id=db_user.id if db_user else None,
                ip_address=ip_address,
                user_agent=user_agent,
                succeeded=False,
                failure_reason=failure_reason,
            )
            if failure_reason == "email_not_verified":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Email not verified",
                )
            return None
        if db_user is None:
            return None

        db_user.last_login_at = _utcnow()
        if verification.valid and verification.needs_rehash:
            old_scheme = verification.scheme or "unknown"
            db_user.password_hash = self._hash_password(password)
            db_user.password_changed_at = _utcnow()
            record_auth_legacy_hash_upgrade(from_scheme=old_scheme, to_scheme=ARGON2_SCHEME)
            logger.info("Upgraded legacy password hash", extra={"user_id": db_user.id, "from_scheme": old_scheme})
        tokens = await self._issue_session_tokens(
            db,
            db_user,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._record_login_attempt(
            db,
            email=normalized_email,
            user_id=db_user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            succeeded=True,
        )
        logger.info("User '%s' authenticated", db_user.email)
        return tokens

    async def refresh_tokens_async(
        self,
        db: AsyncSession,
        refresh_token: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthTokens:
        token_hash = self._hash_opaque_token(refresh_token)
        result = await db.execute(
            select(RefreshToken, UserSession, DBUser)
            .join(UserSession, UserSession.id == RefreshToken.session_id)
            .join(DBUser, DBUser.id == RefreshToken.user_id)
            .where(RefreshToken.token_hash == token_hash)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        refresh_record, session, db_user = row
        now = _utcnow()

        if session.current_refresh_token_id != refresh_record.id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is no longer active")
        if refresh_record.revoked_at is not None or refresh_record.used_at is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been used")
        refresh_expires_at = _as_utc(refresh_record.expires_at)
        session_expires_at = _as_utc(session.expires_at)
        if (refresh_expires_at and refresh_expires_at <= now) or (session_expires_at and session_expires_at <= now):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has expired")
        if session.revoked_at is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")
        if not db_user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account is inactive")

        refresh_record.used_at = now
        refresh_record.last_used_at = now
        refresh_record.revoked_at = now
        refresh_record.revoke_reason = "rotated"

        tokens = await self._issue_session_tokens(
            db,
            db_user,
            ip_address=ip_address,
            user_agent=user_agent,
            session=session,
        )
        refresh_record.replaced_by_token_id = tokens.refresh_token_id
        return tokens

    async def get_current_user_async(self, db: AsyncSession, token: str) -> User:
        payload = self.verify_token(token, expected_type=ACCESS_TOKEN_TYPE)
        user_id = payload.get("sub")
        session_id = payload.get("sid")
        access_jti = payload.get("jti")
        if not user_id or not session_id or not access_jti:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")

        session, db_user = await self._ensure_active_session(db, session_id=session_id, user_id=user_id)
        if session.current_access_jti != access_jti:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token has been revoked")
        access_expires_at = _as_utc(session.access_expires_at)
        if access_expires_at and access_expires_at <= _utcnow():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token has expired")

        session.last_seen_at = _utcnow()
        return self._to_user_context(db_user, session_id=session.id)

    async def logout_async(self, db: AsyncSession, user: User) -> None:
        if not user.session_id:
            return
        session, _ = await self._ensure_active_session(db, session_id=user.session_id, user_id=user.id)
        await self._revoke_session(db, session, "logout")

    async def logout_all_async(self, db: AsyncSession, user: User, *, exclude_session_id: str | None = None) -> int:
        result = await db.execute(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
        )
        sessions = result.scalars().all()
        revoked = 0
        for session in sessions:
            if exclude_session_id and session.id == exclude_session_id:
                continue
            await self._revoke_session(db, session, "logout_all")
            revoked += 1
        return revoked

    async def list_sessions_async(
        self,
        db: AsyncSession,
        *,
        requesting_user: User,
        target_user_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[dict[str, Any]]:
        user_id = target_user_id or requesting_user.id
        if target_user_id and requesting_user.role != "admin" and target_user_id != requesting_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

        query = _build_session_query().where(UserSession.user_id == user_id)
        if not include_revoked:
            query = query.where(UserSession.revoked_at.is_(None))
        query = query.order_by(UserSession.created_at.desc())
        result = await db.execute(query)
        return [self.session_payload(session, db_user) for session, db_user in result.all()]

    async def revoke_session_async(
        self,
        db: AsyncSession,
        *,
        requesting_user: User,
        session_id: str,
    ) -> None:
        result = await db.execute(
            _build_session_query().where(UserSession.id == session_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        session, _db_user = row
        if requesting_user.role != "admin" and session.user_id != requesting_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        await self._revoke_session(db, session, "manual_revoke")

    async def change_password_async(
        self,
        db: AsyncSession,
        *,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        self._validate_password_strength(new_password)
        db_user = await self._get_user_record_by_id(db, user.id)
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        if not self._verify_password(current_password, db_user.password_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
        if self._verify_password(new_password, db_user.password_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")

        db_user.password_hash = self._hash_password(new_password)
        db_user.password_changed_at = _utcnow()
        db_user.must_change_password = False
        db_user.updated_by_user_id = user.id

        await self.logout_all_async(db, user)

    async def forgot_password_async(
        self,
        db: AsyncSession,
        *,
        email: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> str | None:
        db_user = await self._get_user_by_email(db, email)
        if not db_user or not db_user.is_active:
            return None

        now = _utcnow()
        result = await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == db_user.id,
                PasswordResetToken.revoked_at.is_(None),
                PasswordResetToken.used_at.is_(None),
            )
        )
        for token in result.scalars():
            token.revoked_at = now

        raw_token = self._generate_opaque_token("prt")
        db.add(
            PasswordResetToken(
                user_id=db_user.id,
                token_hash=self._hash_opaque_token(raw_token),
                expires_at=self._password_reset_expiry(),
                request_ip=ip_address,
                user_agent=user_agent,
            )
        )
        return raw_token

    async def reset_password_async(
        self,
        db: AsyncSession,
        *,
        reset_token: str,
        new_password: str,
    ) -> None:
        self._validate_password_strength(new_password)
        token_hash = self._hash_opaque_token(reset_token)
        result = await db.execute(
            select(PasswordResetToken, DBUser)
            .join(DBUser, DBUser.id == PasswordResetToken.user_id)
            .where(PasswordResetToken.token_hash == token_hash)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")

        reset_record, db_user = row
        now = _utcnow()
        if reset_record.revoked_at is not None or reset_record.used_at is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token has already been used")
        reset_expires_at = _as_utc(reset_record.expires_at)
        if reset_expires_at and reset_expires_at <= now:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token has expired")
        if not db_user.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User account is inactive")

        db_user.password_hash = self._hash_password(new_password)
        db_user.password_changed_at = now
        db_user.must_change_password = False
        reset_record.used_at = now

        await self.logout_all_async(db, self._to_user_context(db_user))

    # ── User Administration ──────────────────────────────

    @staticmethod
    def _validate_role(role: str) -> str:
        normalized = role.strip().lower()
        if normalized not in ROLE_RANK:
            allowed = ", ".join(sorted(ROLE_RANK))
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Role must be one of: {allowed}")
        return normalized

    async def list_users_async(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(select(DBUser).order_by(DBUser.created_at.asc()))
        return [self.user_payload(self._to_user_context(user)) | {"is_active": user.is_active} for user in result.scalars()]

    async def create_user_async(
        self,
        db: AsyncSession,
        *,
        email: str,
        name: str,
        role: str,
        created_by_user_id: str | None,
        password: str | None = None,
        is_active: bool = True,
    ) -> tuple[DBUser, str | None]:
        normalized_email = _normalize_email(email)
        if await self._get_user_by_email(db, normalized_email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with that email already exists")

        normalized_role = self._validate_role(role)
        generated_password: str | None = None
        if password:
            self._validate_password_strength(password)
        else:
            generated_password = self._generate_opaque_token("pwd")[-20:]
            password = generated_password

        db_user = DBUser(
            email=normalized_email,
            name=name.strip() or normalized_email,
            role=normalized_role,
            password_hash=self._hash_password(password),
            is_active=is_active,
            must_change_password=generated_password is not None,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=created_by_user_id,
        )
        db.add(db_user)
        await db.flush()
        return db_user, generated_password

    async def update_user_async(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        acting_user_id: str | None,
        name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> DBUser:
        db_user = await self._get_user_record_by_id(db, user_id)
        if not db_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if name is not None:
            db_user.name = name.strip() or db_user.name
        if role is not None:
            db_user.role = self._validate_role(role)
        if is_active is not None:
            db_user.is_active = is_active
        if password is not None:
            self._validate_password_strength(password)
            db_user.password_hash = self._hash_password(password)
            db_user.password_changed_at = _utcnow()
            db_user.must_change_password = False
            await self.logout_all_async(db, self._to_user_context(db_user))
        if is_active is False:
            await self.logout_all_async(db, self._to_user_context(db_user))
        db_user.updated_by_user_id = acting_user_id
        await db.flush()
        return db_user

    async def bootstrap_admin_async(
        self,
        db: AsyncSession,
        *,
        email: str,
        password: str,
        name: str = "Administrator",
    ) -> DBUser:
        self._validate_password_strength(password)
        result = await db.execute(select(DBUser.id).limit(1))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Users already exist; bootstrap is closed")
        db_user, _ = await self.create_user_async(
            db,
            email=email,
            name=name,
            role="admin",
            password=password,
            is_active=True,
            created_by_user_id=None,
        )
        db_user.is_verified = True
        db_user.must_change_password = False
        await db.flush()
        return db_user

    # ── Sync Test Helpers ────────────────────────────────

    @staticmethod
    def _run_sync(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        raise RuntimeError("This helper cannot be used inside an active event loop; use the async variant instead.")

    def authenticate(self, email: str, password: str) -> tuple[User, str] | None:
        async def _inner():
            async with async_session_factory() as session:
                result = await self.authenticate_async(session, email, password)
                await session.commit()
                if not result:
                    return None
                return result.user, result.access_token

        return self._run_sync(_inner())

    def get_user_by_id(self, user_id: str) -> User | None:
        async def _inner():
            async with async_session_factory() as session:
                db_user = await self._get_user_record_by_id(session, user_id)
                return self._to_user_context(db_user) if db_user else None

        return self._run_sync(_inner())

    def get_sessions(self) -> list[dict[str, Any]]:
        async def _inner():
            async with async_session_factory() as session:
                result = await session.execute(
                    _build_session_query().order_by(UserSession.created_at.desc())
                )
                return [self.session_payload(db_session, db_user) for db_session, db_user in result.all()]

        return self._run_sync(_inner())


auth_service = AuthService()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not credentials:
        settings = get_settings()
        if settings.app_env != "production" and settings.enable_demo_auth:
            return _local_development_user()
        return None
    return await auth_service.get_current_user_async(db, credentials.credentials)


async def require_admin(
    user: User | None = Depends(get_current_user),
) -> User:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_authenticated_user(
    user: User | None = Depends(get_current_user),
) -> User:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(required_role: str):
    normalized_required = AuthService._validate_role(required_role)

    async def dependency(
        user: User = Depends(require_authenticated_user),
    ) -> User:
        user_rank = ROLE_RANK.get(user.role, -1)
        required_rank = ROLE_RANK[normalized_required]
        if user_rank < required_rank:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency
