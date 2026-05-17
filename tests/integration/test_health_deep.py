from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.config.settings import get_settings


async def test_readyz_reports_components(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "ready.sqlite"
    monkeypatch.setenv("APIBANK_DB_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("APIBANK_FERNET_KEYS", "")
    monkeypatch.setenv("APIBANK_API_KEY_SALT", "ready-salt")
    get_settings.cache_clear()

    import packages.db.session as session_module

    session_module._engine = None
    session_module._sessionmaker = None
    from packages.db.models import Base

    async with session_module.get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["status"] in ("ready", "degraded")
    assert "db" in body["components"]
    assert "redis" in body["components"]

    session_module._engine = None
    session_module._sessionmaker = None
    get_settings.cache_clear()
