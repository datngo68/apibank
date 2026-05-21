"""Multi-admin role matrix — permission dependency.

Hệ thống có 2 tier role:
- ``role``: user-facing (user|admin|owner) — đã có trên User.
- ``admin_role``: tier sub-role admin (super_admin|support|finance|read_only)
  — lưu trong ``users.admin_role_extra`` (nếu có) hoặc default theo
  legacy ``role``: admin/owner → super_admin.

Mỗi endpoint admin gắn 1 permission name (``audit:read``, ``user:delete``,
``billing:refund``, …). Helper ``require_permission(perm)`` raise 403 nếu
admin role không có quyền.

Ma trận permission là static để không cần thêm bảng mới — đơn giản, đủ
cho < 10 admin role; khi cần fine-grained có thể migrate sang DB sau.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status

from packages.db.models import User
from packages.security.user_auth import current_admin_user

# ---------------------------------------------------------------------------
# Permission catalog
# ---------------------------------------------------------------------------

ROLE_SUPER_ADMIN = "super_admin"
ROLE_SUPPORT = "support"
ROLE_FINANCE = "finance"
ROLE_READ_ONLY = "read_only"

ALL_ADMIN_ROLES = (ROLE_SUPER_ADMIN, ROLE_SUPPORT, ROLE_FINANCE, ROLE_READ_ONLY)


# Catalog các permission. Quy ước: "<resource>:<action>".
PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_SUPER_ADMIN: frozenset(
        {
            "user:read",
            "user:update",
            "user:delete",
            "user:impersonate",
            "user:wallet",
            "billing:read",
            "billing:refund",
            "billing:void",
            "subscription:read",
            "subscription:write",
            "plan:write",
            "coupon:write",
            "bank:read",
            "bank:write",
            "order:read",
            "order:write",
            "tx:read",
            "tx:write",
            "webhook:read",
            "webhook:write",
            "system:write",
            "audit:read",
            "audit:export",
            "config:write",
            "broadcast:send",
            "ipblock:write",
        }
    ),
    ROLE_SUPPORT: frozenset(
        {
            "user:read",
            "user:update",
            "user:wallet",
            "subscription:read",
            "subscription:write",
            "billing:read",
            "order:read",
            "order:write",
            "tx:read",
            "webhook:read",
            "audit:read",
            "broadcast:send",
            "bank:read",
        }
    ),
    ROLE_FINANCE: frozenset(
        {
            "user:read",
            "billing:read",
            "billing:refund",
            "billing:void",
            "subscription:read",
            "plan:write",
            "coupon:write",
            "audit:read",
            "audit:export",
        }
    ),
    ROLE_READ_ONLY: frozenset(
        {
            "user:read",
            "subscription:read",
            "billing:read",
            "order:read",
            "tx:read",
            "webhook:read",
            "audit:read",
            "bank:read",
        }
    ),
}


def resolve_admin_role(user: User) -> str:
    """Map User → admin_role.

    Hiện tại: admin/owner đều coi là super_admin (legacy). Khi DB có
    ``admin_role_extra`` (cột thêm sau), nên đọc từ đó.
    """
    extra = getattr(user, "admin_role_extra", None)
    if extra in ALL_ADMIN_ROLES:
        return str(extra)
    if user.role in ("admin", "owner"):
        return ROLE_SUPER_ADMIN
    return ROLE_READ_ONLY


def has_permission(user: User, permission: str) -> bool:
    role = resolve_admin_role(user)
    return permission in PERMISSIONS.get(role, frozenset())


def require_permission(permission: str) -> Callable[..., Awaitable[User]]:
    """Dependency factory: raise 403 nếu admin không có permission."""

    async def dependency(user: User = Depends(current_admin_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permission: {permission}",
            )
        return user

    return dependency


__all__ = [
    "ALL_ADMIN_ROLES",
    "PERMISSIONS",
    "ROLE_FINANCE",
    "ROLE_READ_ONLY",
    "ROLE_SUPER_ADMIN",
    "ROLE_SUPPORT",
    "has_permission",
    "require_permission",
    "resolve_admin_role",
]
