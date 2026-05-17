"""`apimb fernet generate` — sinh khóa Fernet."""

from __future__ import annotations

import argparse


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("fernet", help="manage fernet keys")
    pp = p.add_subparsers(dest="action", required=True)
    gen = pp.add_parser("generate", help="print a new fernet key")
    gen.set_defaults(func=run)


def run(_: argparse.Namespace) -> int:
    from packages.security.crypto import FernetCipher

    print(FernetCipher.generate_key())
    return 0
