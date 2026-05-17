"""Sinh OpenAPI JSON từ FastAPI app, ghi ra `docs/openapi.json`.

Chạy:
    python scripts/dump_openapi.py

CI có thể chạy script này rồi git diff để fail nếu schema thay đổi mà không
được commit.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Đặt env tối thiểu để Settings không raise ở local — script này không cần DB.
os.environ.setdefault("APIBANK_DB_URL", "sqlite+aiosqlite:///./apibank.db")
os.environ.setdefault("APIBANK_API_KEY_SALT", "dev-only-change-me")
os.environ.setdefault("APIBANK_FERNET_KEYS", "")
os.environ.setdefault("APIBANK_LOG_LEVEL", "WARNING")


def main() -> None:
    from apps.api.main import create_app

    app = create_app()
    schema = app.openapi()
    out = ROOT / "docs" / "openapi.json"
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
