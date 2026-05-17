"""`apimb migrate` — wrap alembic upgrade/downgrade."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("migrate", help="run database migrations")
    p.add_argument("--target", default="head", help="alembic target (default: head)")
    p.add_argument(
        "--downgrade",
        action="store_true",
        help="downgrade to --target instead of upgrade",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "-m", "alembic"]
    cmd.append("downgrade" if args.downgrade else "upgrade")
    cmd.append(args.target)
    print(f"$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, env=os.environ.copy())  # noqa: S603
