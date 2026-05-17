"""apimb CLI — entry point để vận hành toàn bộ APIBank.

Subcommands:
- start             Chạy API + worker + scheduler + dispatcher trên 1 process.
- dev               Chạy uvicorn --reload + vite dev song song.
- migrate           alembic upgrade/downgrade.
- user              create/list/promote.
- plan              seed/list.
- system-bank       set --account-id ...
- fernet            generate.
- api-key           create.
- bank-account      create.
- doctor            kiểm tra môi trường.
- version           in version.

Giữ alias `apibank` cho tài liệu cũ; trỏ vào cùng entry point.
"""

from __future__ import annotations

import argparse
import sys

from apps.cli import apikey as apikey_cmd
from apps.cli import bank, doctor, fernet, migrate, plan, start, system_bank, user, version
from apps.cli import dev as dev_cmd


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apimb",
        description="APIBank CLI — vận hành cổng nhận tiền tự host.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"apimb {version.VERSION}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start.register(sub)
    dev_cmd.register(sub)
    migrate.register(sub)
    user.register(sub)
    plan.register(sub)
    system_bank.register(sub)
    fernet.register(sub)
    apikey_cmd.register(sub)
    bank.register(sub)
    doctor.register(sub)
    version.register(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    try:
        return int(func(args) or 0)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


__all__ = ["main"]
