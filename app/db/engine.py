"""Async engine и фабрика сессий."""
from __future__ import annotations
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from app.config import settings

engine: AsyncEngine = create_async_engine(
    settings.database_url, echo=False, pool_pre_ping=True, pool_size=10, max_overflow=5,
)
SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False,
)

@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

async def dispose_engine() -> None:
    await engine.dispose()