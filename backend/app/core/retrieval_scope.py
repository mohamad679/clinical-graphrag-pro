"""Typed retrieval authorization scope.

User-facing retrieval must carry this object so tenant, principal user,
patient, and organization fields cannot be treated as interchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    tenant_id: str
    principal_user_id: str
    patient_id: str | None = None
    organization_id: str | None = None
    is_admin: bool = False

    def __post_init__(self) -> None:
        if not str(self.tenant_id or "").strip():
            raise ValueError("RetrievalScope.tenant_id is required.")
        if not str(self.principal_user_id or "").strip():
            raise ValueError("RetrievalScope.principal_user_id is required.")

    def to_filters(self) -> dict[str, str]:
        filters = {
            "tenant_id": str(self.tenant_id),
            "user_id": str(self.principal_user_id),
        }
        if self.patient_id:
            filters["patient_id"] = str(self.patient_id)
        if self.organization_id:
            filters["organization_id"] = str(self.organization_id)
        return filters


def retrieval_scope_for_user(
    user,
    *,
    patient_id: str | None = None,
    organization_id: str | None = None,
) -> RetrievalScope:
    tenant_id = getattr(user, "tenant_id", None) or getattr(user, "id")
    return RetrievalScope(
        tenant_id=str(tenant_id),
        principal_user_id=str(getattr(user, "id")),
        patient_id=patient_id,
        organization_id=organization_id,
        is_admin=getattr(user, "role", None) == "admin",
    )


def exact_scope_match(metadata: dict | None, filters: dict | None) -> bool:
    meta = metadata or {}
    for key, value in (filters or {}).items():
        if value is None:
            continue
        if str(meta.get(key)) != str(value):
            return False
    return True
