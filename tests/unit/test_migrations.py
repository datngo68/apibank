"""Verify migrations upgrade/downgrade round-trip and produce schema matching ORM."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _run_alembic(args: list[str], db_url: str, repo_root: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "APIBANK_DB_URL": db_url,
        "APIBANK_FERNET_KEYS": "",
        "APIBANK_API_KEY_SALT": "test-salt",
        "PATH": "",
    }
    import os

    env_full = os.environ.copy()
    env_full.update(env)
    return subprocess.run(
        ["python", "-m", "alembic", *args],
        cwd=str(repo_root),
        env=env_full,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture()
def fresh_sqlite_url(tmp_path: Path) -> str:
    db = tmp_path / "alembic_test.db"
    if db.exists():
        db.unlink()
    return f"sqlite+aiosqlite:///{db.as_posix()}"


def test_upgrade_head_then_downgrade_base(fresh_sqlite_url: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    up = _run_alembic(["upgrade", "head"], fresh_sqlite_url, repo_root)
    assert up.returncode == 0, f"upgrade failed:\n{up.stderr}"
    assert "0003_saas" in up.stderr or "Running upgrade" in up.stderr

    down = _run_alembic(["downgrade", "base"], fresh_sqlite_url, repo_root)
    assert down.returncode == 0, f"downgrade failed:\n{down.stderr}"

    # Re-upgrade phải pass: round-trip ổn định
    up2 = _run_alembic(["upgrade", "head"], fresh_sqlite_url, repo_root)
    assert up2.returncode == 0, f"second upgrade failed:\n{up2.stderr}"


def test_schema_matches_models(fresh_sqlite_url: str) -> None:
    """Sau upgrade head, mọi bảng ORM phải tồn tại với cột cốt lõi."""
    repo_root = Path(__file__).resolve().parents[2]
    up = _run_alembic(["upgrade", "head"], fresh_sqlite_url, repo_root)
    assert up.returncode == 0

    import sqlite3

    db_path = fresh_sqlite_url.replace("sqlite+aiosqlite:///", "")
    if shutil.which("sqlite3"):
        # tránh phụ thuộc CLI; dùng python sqlite3
        pass
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()

    expected = {
        "users",
        "sessions",
        "email_tokens",
        "two_factors",
        "oauth_identities",
        "plans",
        "subscriptions",
        "invoices",
        "wallet_transactions",
        "notifications",
        "notification_preferences",
        "bank_accounts",
        "orders",
        "transactions",
        "webhooks",
        "api_keys",
        "audit_logs",
        "alembic_version",
    }
    missing = expected - tables
    assert not missing, f"Missing tables after migration: {missing}"


def test_users_columns_present(fresh_sqlite_url: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    _run_alembic(["upgrade", "head"], fresh_sqlite_url, repo_root)
    import sqlite3

    db_path = fresh_sqlite_url.replace("sqlite+aiosqlite:///", "")
    conn = sqlite3.connect(db_path)
    try:
        info = conn.execute("PRAGMA table_info(users)").fetchall()
    finally:
        conn.close()
    cols = {row[1] for row in info}
    for required in (
        "id",
        "email",
        "password_hash",
        "role",
        "balance_vnd",
        "telegram_chat_id",
        "failed_login_count",
        "locked_until",
        "deleted_at",
    ):
        assert required in cols, f"users.{required} missing"


def test_bank_accounts_have_user_id_and_system_flag(fresh_sqlite_url: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    _run_alembic(["upgrade", "head"], fresh_sqlite_url, repo_root)
    import sqlite3

    db_path = fresh_sqlite_url.replace("sqlite+aiosqlite:///", "")
    conn = sqlite3.connect(db_path)
    try:
        info = conn.execute("PRAGMA table_info(bank_accounts)").fetchall()
    finally:
        conn.close()
    cols = {row[1] for row in info}
    assert "user_id" in cols
    assert "is_system_account" in cols
    assert "polling_status" in cols
    assert "verified_at" in cols
