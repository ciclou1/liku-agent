from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_active_database_profile, get_settings


settings = get_settings()
active_database_url = get_active_database_profile(settings)["database_url"]
# aiomysql 0.2 exposes an async ping signature that SQLAlchemy's generic
# pool_pre_ping hook cannot call. Recycle connections instead and let the
# request fail/retry at the service boundary when a server closes one.
engine = create_async_engine(active_database_url, pool_pre_ping=False, pool_recycle=1800)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


async def dispose_db() -> None:
    await engine.dispose()
