"""apimb version."""

from __future__ import annotations

import argparse
import platform
import sys

VERSION = "0.1.0"


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("version", help="show version info")
    p.set_defaults(func=run)


def run(_: argparse.Namespace) -> int:
    print(f"apimb {VERSION}")
    print(f"python {sys.version.split()[0]}")
    print(f"platform {platform.platform()}")
    return 0
