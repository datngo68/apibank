"""User-side auth dependencies (cookie session, không phải Bearer API key).

Khác với `dependencies.py` (xác thực API key cho /v1/*), file này phục vụ /api/v1/auth
và /api/v1/me/* — flow trình duyệt với cookie httpOnly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Session as SessionModel
from packages.db.models import User
from packages.db.session import get_session
from packages.security.sessions import COOKIE_NAME, lookup_session, touch_session


async def _resolve_session(
    request: Request, session: AsyncSession
) -> tuple[SessionModel, User] | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    return await lookup_session(session, raw)


async def optional_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    pair = await _resolve_session(request, session)
    if pair is None:
        return None
    sess, user = pair
    request.state.user_id = user.id
    request.state.session_id = sess.id
    await touch_session(session, sess, ip=request.client.host if request.client else None)
    await session.commit()
    return user


async def current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User:
    user = await optional_current_user(request, session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    return user


def require_role(*roles: str) -> Callable[[User], Awaitable[User]]:
    """Decorator dùng làm Depends() để giới hạn theo role."""

    allowed = {r.lower() for r in roles}

    async def dependency(user: User = Depends(current_user)) -> User:
        if user.role.lower() not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role"
            )
        return user

    return dependency


require_admin = require_role("admin", "owner")


async def current_admin_user(user: User = Depends(current_user)) -> User:
    """Dependency cho /api/v1/admin/* — chặn user thường."""
    if user.role not in ("admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin only"
        )
    return user
