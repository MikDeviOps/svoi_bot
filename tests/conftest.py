"""Фикстуры pytest-asyncio.

- ``settings`` — Settings из ENV.
- ``session`` — async-сессия к тестовой БД. Каждый тест — в транзакции,
  после — rollback (быстро, изолированно).
- ``db_engine`` — engine на тестовую БД. Создаёт схему через Alembic
  при первом запуске (опционально, см. ниже).

Тестовая БД: ``DATABASE_URL_TEST`` или ``DATABASE_URL`` с суффиксом ``_test``.
Для Шага 2 (только pydantic-валидаторы) БД не нужна, но фикстура готова
к Шагу 3 (сервисы).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.db import Base


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def event_loop():
    """Один event loop на всю сессию (требование pytest-asyncio)."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Engine на тестовую БД. Схема создаётся через ``Base.metadata.create_all``.

    На Шаге 3, когда появятся сервисы, здесь можно перейти на
    ``alembic upgrade head`` против тестовой БД — но для тестов
    ``create_all`` быстрее и достаточно.
    """
    engine = create_async_engine(settings.test_database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия на тест в транзакции с rollback после.

    Вложенный transaction + rollback: тест не оставляет следов в БД.
    """
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with session_factory() as s:
            yield s
        await trans.rollback()


# ---------------------------------------------------------------------------
# Фабрики
# ---------------------------------------------------------------------------


@pytest.fixture
def make_user():
    """Фабрика пользователей. Возвращает функцию (tg_id, username, full_name)."""

    async def _make(
        session: AsyncSession,
        tg_id: int = 1001,
        username: str = "user",
        full_name: str = "Test User",
    ):
        from app.db import User

        user = User(tg_id=tg_id, username=username, full_name=full_name)
        session.add(user)
        await session.flush()
        return user

    return _make