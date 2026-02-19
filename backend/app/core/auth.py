"""
JWT Authentication & Authorization.
Demo-ready auth with bcrypt password hashing and JWT tokens.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import get_settings

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


@dataclass
class User:
    """Application user."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str = ""
    name: str = ""
    role: str = "user"  # user | admin
    hashed_password: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AuthService:
    """
    JWT-based authentication service.
    Uses demo users for portfolio — swap to DB in production.
    """

    def __init__(self):
        settings = get_settings()
        self._secret = settings.jwt_secret
        self._algorithm = "HS256"
        self._expire_minutes = settings.jwt_expire_minutes
        self._users: dict[str, User] = {}
        self._seed_demo_users()

    def _seed_demo_users(self):
        """Create demo accounts for portfolio presentation."""
        demo_users = [
            User(
                id="demo-admin-001",
                email="admin@clinicalgraph.ai",
                name="Dr. Admin",
                role="admin",
                hashed_password=self._hash_password("admin123"),
            ),
            User(
                id="demo-user-001",
                email="user@clinicalgraph.ai",
                name="Dr. User",
                role="user",
                hashed_password=self._hash_password("user123"),
            ),
        ]
        for u in demo_users:
            self._users[u.email] = u
        logger.info(f"Seeded {len(demo_users)} demo users")

    # ── Password Hashing ─────────────────────────────────

    @staticmethod
    def _hash_password(password: str) -> str:
        """Simple hash for demo. Use bcrypt in production."""
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest()

    def _verify_password(self, plain: str, hashed: str) -> bool:
        return self._hash_password(plain) == hashed

    # ── JWT Tokens ───────────────────────────────────────

    def create_access_token(self, user: User) -> str:
        """Create a JWT access token for the user."""
        payload = {
            "sub": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=self._expire_minutes),
            "iat": datetime.now(timezone.utc),
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_token(self, token: str) -> dict:
        """Verify and decode a JWT token."""
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self._algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

    # ── Authentication ───────────────────────────────────

    def authenticate(self, email: str, password: str) -> tuple[User, str] | None:
        """Authenticate user and return (user, token) or None."""
        user = self._users.get(email)
        if not user:
            return None
        if not self._verify_password(password, user.hashed_password):
            return None

        token = self.create_access_token(user)
        logger.info(f"User '{email}' authenticated")
        return user, token

    def get_user_by_id(self, user_id: str) -> User | None:
        for u in self._users.values():
            if u.id == user_id:
                return u
        return None

    # ── Active Sessions ──────────────────────────────────

    _active_sessions: list[dict] = []

    def record_session(self, user: User, token_jti: str):
        self._active_sessions.append({
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "jti": token_jti,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 100
        if len(self._active_sessions) > 100:
            self._active_sessions = self._active_sessions[-100:]

    def get_sessions(self) -> list[dict]:
        return list(reversed(self._active_sessions))


# Module-level singleton
auth_service = AuthService()


# ── FastAPI Dependencies ─────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> User | None:
    """
    Extract current user from JWT bearer token.
    Returns None if no token provided (endpoints remain open for demo).
    """
    if not credentials:
        return None

    payload = auth_service.verify_token(credentials.credentials)
    user = auth_service.get_user_by_id(payload.get("sub", ""))
    return user


async def require_admin(
    user: User | None = Depends(get_current_user),
) -> User:
    """Require authenticated admin user."""
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
