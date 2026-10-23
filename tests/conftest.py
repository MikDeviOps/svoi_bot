"""Фикстуры pytest-asyncio.

Тестовая БД создаётся автоматически (вариант A):
- подключаемся к системной ``postgres`` DB, ``CREATE DATABASE svoi_test``,
  если её ещё нет;
- создаём схему через ``Base.metadata.drop_all`` + ``create_all``
  (для тестов быстрее, чем Alembic);
- каждый тест — в транзакции с rollback после, чтобы тесты не влияли
  друг на друга и не оставляли данных в БД.

URL тестовой БД: ``DATABASE_URL_TEST`` из ENV, либо ``DATABASE_URL``
с суффиксом ``_test`` (см. ``Settings.test_database_url``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.db import Base, Event, KnownGroup, Signup, User


# ---------------------------------------------------------------------------
# Bootstrap test DB
# ---------------------------------------------------------------------------


def _split_asyncpg_url(url: str) -> tuple[str, str, str, int, str]:
    """Разбить ``postgresql+asyncpg://user:pass@host:port/db`` на части.

    Возвращает ``(user, password, host, port, database)``.
    """
    without_scheme = url.split("://", 1)[1]
    creds, rest = without_scheme.split("@", 1)
    user, _, password = creds.partition(":")
    host_port, _, database = rest.partition("/")
    host, _, port = host_port.partition(":")
    return user, password, host, int(port or 5432), database


async def _ensure_test_db(settings: Settings) -> None:
    """Создать ``svoi_test``, если её нет. Подключаемся к системной ``postgres``."""
    user, password, host, port, database = _split_asyncpg_url(
        settings.test_database_url
    )
    conn = await asyncpg.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", database
        )
        if not exists:
            # Имя БД не параметризуется — экранируем кавычками.
            await conn.execute(f'CREATE DATABASE "{database}"')
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Настройки из ENV, единые на всю сессию."""
    return get_settings()


@pytest_asyncio.fixture(scope="session")
async def db_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Engine на тестовую БД + чистая схема ``create_all``.

    ``NullPool`` — не держим соединения между тестами, чтобы ``drop_all``
    в конце сессии проходил без «connection is in use».
    """
    await _ensure_test_db(settings)

    engine = create_async_engine(
        settings.test_database_url,
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Сессия на тест в транзакции с rollback после.

    Транзакция оборачивает весь тест: изменения видны внутри, но после
    ``rollback`` не остаются в БД.
    """
    async with db_engine.connect() as conn:
        trans = await conn.begin()
        factory = async_sessionmaker(bind=conn, expire_on_commit=False)
        async with factory() as s:
            try:
                yield s
            finally:
                await trans.rollback()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def make_user(
    session: AsyncSession,
) -> Callable[..., Awaitable[User]]:
    """Фабрика пользователей. ``await make_user(tg_id=..., ...)``."""

    async def _make(
        tg_id: int = 1001,
        username: str = "user",
        full_name: str = "Test User",
    ) -> User:
        user = User(tg_id=tg_id, username=username, full_name=full_name)
        session.add(user)
        await session.flush()
        return user

    return _make


@pytest_asyncio.fixture
async def make_event(
    session: AsyncSession,
) -> Callable[..., Awaitable[Event]]:
    """Фабрика встреч.

    Если ``source_chat_id`` задан, создаёт соответствующую ``KnownGroup``
    (иначе нарушится FK ``events.source_chat_id → known_groups.chat_id``).
    """

    async def _make(
        owner_id: int,
        *,
        title: str = "Test Event",
        description: str = "",
        category: str = "games",
        capacity: int = 10,
        visibility: str = "public",
        source_chat_id: int | None = None,
        source_chat_title: str = "Test Group",
        starts_in_days: int = 1,
        address: str = "ул. Тестовая, 1",
        conditions: str = "бесплатно",
    ) -> Event:
        # FK: events.source_chat_id → known_groups.chat_id
        if source_chat_id is not None:
            existing = await session.get(KnownGroup, source_chat_id)
            if existing is None:
                session.add(KnownGroup(chat_id=source_chat_id, title=source_chat_title))
                await session.flush()

        event = Event(
            owner_id=owner_id,
            title=title,
            description=description,
            category=category,
            starts_at=datetime.now(get_settings().timezone)
            + timedelta(days=starts_in_days),
            address=address,
            conditions=conditions,
            capacity=capacity,
            visibility=visibility,
            source_chat_id=source_chat_id,
            source_chat_title=source_chat_title,
        )
        session.add(event)
        await session.flush()
        await session.refresh(event)
        return event

    return _make


@pytest_asyncio.fixture
async def make_signup(
    session: AsyncSession,
) -> Callable[..., Awaitable[Signup]]:
    """Фабрика записей. ``await make_signup(event_id, user_id)``."""

    async def _make(event_id: int, user_id: int) -> Signup:
        s = Signup(event_id=event_id, user_id=user_id, telegram_name="test")
        session.add(s)
        await session.flush()
        return s

    return _make