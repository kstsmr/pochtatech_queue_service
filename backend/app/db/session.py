from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.config import settings

engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)


async def get_connection() -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as connection:
        yield connection


async def close_engine() -> None:
    await engine.dispose()
