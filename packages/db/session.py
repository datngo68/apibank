from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from packages.config.settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = get_settings().db_url
        # SQLite (aiosqlite) dùng StaticPool/connection-per-thread; pool args
        # của Postgres không áp dụng và sẽ raise. Chỉ tune cho non-SQLite.
        if url.startswith("sqlite"):
            _engine = create_async_engine(url, pool_pre_ping=True)
        else:
            _engine = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=20,
                max_overflow=20,
                pool_recycle=1800,
                pool_timeout=10,
            )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
