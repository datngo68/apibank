"""`apimb doctor` — kiểm tra môi trường để chuẩn bị production.

Mỗi check trả `(ok, message, hint)`. ✓ in ra; ✗ thì in thêm gợi ý fix.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NamedTuple


class CheckResult(NamedTuple):
    ok: bool
    label: str
    detail: str = ""
    hint: str | None = None


CheckFn = Callable[[], Awaitable[CheckResult]]


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("doctor", help="diagnose environment readiness")
    p.set_defaults(func=lambda args: asyncio.run(run(args)))


async def run(_: argparse.Namespace) -> int:
    checks: list[CheckFn] = [
        check_python_version,
        check_node_version,
        check_env_file,
        check_fernet_keys,
        check_db_connect,
        check_alembic_head,
        check_redis,
        check_plans_seeded,
        check_system_bank,
        check_admin_user,
        check_web_dist,
        check_smtp_optional,
    ]
    failures = 0
    for fn in checks:
        try:
            res = await fn()
        except Exception as exc:  # noqa: BLE001
            res = CheckResult(False, fn.__name__, f"exception: {exc!r}")
        marker = "✓" if res.ok else "✗"
        print(f"{marker} {res.label}: {res.detail}")
        if not res.ok and res.hint:
            print(f"   ↳ gợi ý: {res.hint}")
        if not res.ok:
            failures += 1
    print()
    print(f"Tổng kết: {len(checks) - failures}/{len(checks)} OK")
    return 1 if failures else 0


# --------------------------------------------------------------------------


async def check_python_version() -> CheckResult:
    ok = sys.version_info >= (3, 12)
    return CheckResult(ok, "Python ≥ 3.12", sys.version.split()[0])


async def check_node_version() -> CheckResult:
    import shutil
    import subprocess

    npm = shutil.which("node")
    if npm is None:
        return CheckResult(False, "Node.js", "không tìm thấy", "cài Node 20+")
    out = subprocess.run(  # noqa: ASYNC221, S603
        [npm, "--version"], capture_output=True, text=True, check=False
    )
    return CheckResult(out.returncode == 0, "Node.js", out.stdout.strip())


async def check_env_file() -> CheckResult:
    path = Path(".env")
    return CheckResult(path.exists(), ".env", str(path), "copy .env.example → .env")  # noqa: ASYNC240


async def check_fernet_keys() -> CheckResult:
    from packages.config.settings import get_settings

    keys = get_settings().fernet_keys
    if not keys:
        return CheckResult(False, "APIBANK_FERNET_KEYS", "trống", "apimb fernet generate")
    return CheckResult(True, "APIBANK_FERNET_KEYS", "đã set")


async def check_db_connect() -> CheckResult:
    from sqlalchemy import text

    from packages.db.session import get_sessionmaker

    try:
        sm = get_sessionmaker()
        async with sm() as session:
            await session.execute(text("SELECT 1"))
        return CheckResult(True, "DB connect", "OK")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, "DB connect", repr(exc), "kiểm tra APIBANK_DB_URL")


async def check_alembic_head() -> CheckResult:
    """Có ít nhất 1 row trong alembic_version (đã apply migration)."""
    from sqlalchemy import text

    from packages.db.session import get_sessionmaker

    try:
        sm = get_sessionmaker()
        async with sm() as session:
            res = await session.execute(text("SELECT version_num FROM alembic_version"))
            rev = res.scalar_one_or_none()
        if rev:
            return CheckResult(True, "Alembic head", str(rev))
        return CheckResult(False, "Alembic head", "chưa apply migration", "apimb migrate")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, "Alembic head", repr(exc), "apimb migrate")


async def check_redis() -> CheckResult:
    from collections.abc import Awaitable
    from typing import Any, cast

    from redis.asyncio import Redis

    from packages.config.settings import get_settings

    try:
        redis = Redis.from_url(get_settings().redis_url)
        await cast(Awaitable[Any], redis.ping())
        await redis.aclose()
        return CheckResult(True, "Redis", "OK")
    except Exception:
        return CheckResult(
            False,
            "Redis",
            "không kết nối được",
            "Optional. Chạy `docker run -p 6379:6379 redis` hoặc dùng fallback in-memory.",
        )


async def check_plans_seeded() -> CheckResult:
    from sqlalchemy import func, select

    from packages.db.models import Plan
    from packages.db.session import get_sessionmaker

    try:
        sm = get_sessionmaker()
        async with sm() as session:
            count = await session.scalar(
                select(func.count()).select_from(Plan).where(Plan.active.is_(True))
            )
        if int(count or 0) == 0:
            return CheckResult(False, "Plans", "chưa seed", "apimb plan seed")
        return CheckResult(True, "Plans", f"{count} plan active")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, "Plans", repr(exc))


async def check_system_bank() -> CheckResult:
    from sqlalchemy import select

    from packages.db.models import BankAccount
    from packages.db.session import get_sessionmaker

    try:
        sm = get_sessionmaker()
        async with sm() as session:
            row = (
                await session.scalars(
                    select(BankAccount).where(BankAccount.is_system_account.is_(True))
                )
            ).first()
        if row is None:
            return CheckResult(
                False,
                "System bank",
                "chưa cấu hình",
                "apimb system-bank set --account-id ba_xxx",
            )
        return CheckResult(True, "System bank", f"{row.bank_code}/{row.account_no}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, "System bank", repr(exc))


async def check_admin_user() -> CheckResult:
    from sqlalchemy import func, select

    from packages.db.models import User
    from packages.db.session import get_sessionmaker

    try:
        sm = get_sessionmaker()
        async with sm() as session:
            count = await session.scalar(
                select(func.count()).select_from(User).where(User.role.in_(("admin", "owner")))
            )
        if int(count or 0) == 0:
            return CheckResult(
                False,
                "Admin user",
                "chưa có",
                "apimb user create --email admin@local --admin",
            )
        return CheckResult(True, "Admin user", f"{count} user(s)")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, "Admin user", repr(exc))


async def check_web_dist() -> CheckResult:
    path = Path("apps/web/dist/index.html")
    if not path.exists():  # noqa: ASYNC240
        return CheckResult(
            False,
            "Web dist",
            "chưa build",
            "cd apps/web && npm install && npm run build",
        )
    return CheckResult(True, "Web dist", str(path))


async def check_smtp_optional() -> CheckResult:
    from packages.config.settings import get_settings

    s = get_settings()
    host = getattr(s, "smtp_host", "") or ""
    if not host:
        return CheckResult(True, "SMTP", "không cấu hình (email channel sẽ tắt)")
    return CheckResult(True, "SMTP", f"{host}:{getattr(s, 'smtp_port', 587)}")


# Để giữ API ổn định nếu test import
_ = os
