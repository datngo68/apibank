"""Bootstrap local environment: init DB schema, generate Fernet key, create API key.

Usage (from project root, with venv active):

    python scripts/bootstrap_local.py \\
        --mb-username 0123456789 --mb-password "***" \\
        --mb-account-no 0011223344 --mb-holder "NGUYEN VAN A"

What it does:
    1. Generates a Fernet key if APIBANK_FERNET_KEYS is empty in .env
    2. Generates APIBANK_API_KEY_SALT if missing
    3. Writes/updates .env file
    4. Creates SQLite tables from SQLAlchemy metadata (no Alembic needed for local)
    5. Inserts the bank account (encrypted)
    6. Creates an API key with all scopes for testing
    7. Optionally inserts a webhook destination (https://webhook.site/<your_uuid>)

Prints the API key + webhook secret. Save them; the API key won't be retrievable again.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from pathlib import Path

ENV_FILE = Path(".env")


def _read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    pairs: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def _write_env(pairs: dict[str, str]) -> None:
    body = "\n".join(f"{key}={value}" for key, value in pairs.items()) + "\n"
    ENV_FILE.write_text(body, encoding="utf-8")


def ensure_secrets(env: dict[str, str]) -> dict[str, str]:
    from packages.security.crypto import FernetCipher

    if not env.get("APIBANK_FERNET_KEYS"):
        env["APIBANK_FERNET_KEYS"] = f"primary:{FernetCipher.generate_key()}"
    if not env.get("APIBANK_API_KEY_SALT") or env["APIBANK_API_KEY_SALT"].startswith("CHANGE"):
        env["APIBANK_API_KEY_SALT"] = secrets.token_urlsafe(32)
    env.setdefault("APIBANK_DB_URL", "sqlite+aiosqlite:///./apibank.db")
    env.setdefault("APIBANK_REDIS_URL", "redis://localhost:6379/0")
    env.setdefault("APIBANK_LOG_LEVEL", "INFO")
    env.setdefault("APIBANK_POLL_INTERVAL", "20")
    env.setdefault("APIBANK_WEBHOOK_MAX_ATTEMPTS", "7")
    env.setdefault("APIBANK_SENTRY_DSN", "")
    return env


async def init_db_and_seed(args: argparse.Namespace) -> dict[str, str]:
    from packages.banks.base import BankAdapter  # noqa: F401  ensure registry imports work
    from packages.config.settings import get_settings
    from packages.db.models import BankAccount, Base, Webhook
    from packages.db.session import get_engine, get_sessionmaker
    from packages.security.bootstrap import create_api_key
    from packages.security.crypto import FernetCipher

    get_settings.cache_clear()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = get_settings()
    cipher = FernetCipher.from_keys(settings.fernet_keys)
    sessionmaker = get_sessionmaker()
    output: dict[str, str] = {}

    async with sessionmaker() as session:
        bank_account = BankAccount(
            bank_code="MB",
            account_no=args.mb_account_no,
            account_holder=args.mb_holder,
            credentials_enc=cipher.encrypt(f"{args.mb_username}:{args.mb_password}"),
            status="active",
            polling_enabled=True,
        )
        session.add(bank_account)
        raw_key, _ = await create_api_key(
            session,
            owner_id="default",
            scopes=["orders:write", "orders:read", "transactions:read", "admin:*"],
        )
        webhook_secret = secrets.token_urlsafe(32)
        if args.webhook_url:
            session.add(
                Webhook(
                    owner_id="default",
                    url=args.webhook_url,
                    secret_enc=cipher.encrypt(webhook_secret),
                    active=True,
                    headers_json={},
                )
            )
        await session.commit()
        await session.refresh(bank_account)
        output["bank_account_id"] = bank_account.id
        output["api_key"] = raw_key
        if args.webhook_url:
            output["webhook_url"] = args.webhook_url
            output["webhook_secret"] = webhook_secret
    await engine.dispose()
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mb-username", required=True)
    parser.add_argument("--mb-password", required=True)
    parser.add_argument("--mb-account-no", required=True)
    parser.add_argument("--mb-holder", required=True)
    parser.add_argument("--webhook-url", default="")
    args = parser.parse_args()

    env = ensure_secrets(_read_env())
    _write_env(env)
    for key, value in env.items():
        os.environ.setdefault(key, value)
    os.environ["APIBANK_FERNET_KEYS"] = env["APIBANK_FERNET_KEYS"]
    os.environ["APIBANK_API_KEY_SALT"] = env["APIBANK_API_KEY_SALT"]
    os.environ["APIBANK_DB_URL"] = env["APIBANK_DB_URL"]

    output = asyncio.run(init_db_and_seed(args))
    print(json.dumps(output, indent=2))
    print("\nSaved .env. Save the API key shown above - it cannot be recovered.")


if __name__ == "__main__":
    main()
