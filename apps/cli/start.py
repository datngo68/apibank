"""`apimb start` — chạy uvicorn với embedded workers + tray icon.

Mặc định Windows/macOS sẽ thu nhỏ vào tray hệ thống. Dùng `--no-tray` để
chạy console kiểu cũ (CI / Linux server không có DE).
"""

from __future__ import annotations

import argparse
import sys


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "start",
        help="run API + embedded worker/scheduler/dispatcher",
    )
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--no-embed", action="store_true", help="disable embedded workers")
    p.add_argument(
        "--no-tray",
        action="store_true",
        help="chạy console thay vì tray icon (Linux server / CI)",
    )
    p.add_argument("--reload", action="store_true", help="enable uvicorn reload (dev only)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from apps.cli.tray import run_console, run_with_tray

    embed = not args.no_embed
    use_tray = (
        not args.no_tray
        and not args.reload  # reload mode không hợp với tray (subprocess)
        and sys.platform in ("win32", "darwin")
    )

    if use_tray:
        return run_with_tray(
            host=args.host,
            port=args.port,
            embed_workers=embed,
            workers=args.workers,
        )

    return run_console(
        host=args.host,
        port=args.port,
        embed_workers=embed,
        workers=args.workers,
        reload=args.reload,
    )
