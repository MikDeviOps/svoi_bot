"""Тесты UserUpsertMiddleware: create, update, no_race."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import User
from app.middlewares import UserUpsertMiddleware


class _FakeUser:
    def __init__(self, tg_id: int, username: str = "", full_name: str = ""):
        self.id = tg_id
        self.username = username
        self.full_name = full_name


@pytest.mark.asyncio
async def test_upsert_creates_user(session):
    mw = UserUpsertMiddleware()
    tg_user = _FakeUser(123, "test", "Test User")
    data = {"event_from_user": tg_user, "session": session}

    handler = AsyncMock(return_value="ok")
    result = await mw(handler, MagicMock(), data)

    assert result == "ok"
    user = await session.get(User, 123)
    assert user is not None
    assert user.username == "test"
    assert user.full_name == "Test User"


@pytest.mark.asyncio
async def test_upsert_updates_existing(session):
    session.add(User(tg_id=123, username="old", full_name="Old Name"))
    await session.flush()

    mw = UserUpsertMiddleware()
    tg_user = _FakeUser(123, "new", "New Name")
    data = {"event_from_user": tg_user, "session": session}

    handler = AsyncMock(return_value="ok")
    await mw(handler, MagicMock(), data)

    user = await session.get(User, 123)
    assert user.username == "new"
    assert user.full_name == "New Name"


@pytest.mark.asyncio
async def test_upsert_no_race(session):
    """Два upsert подряд от одного tg_id не падают (ON CONFLICT)."""
    mw = UserUpsertMiddleware()
    tg_user = _FakeUser(456, "x", "X")
    data = {"event_from_user": tg_user, "session": session}

    await mw(AsyncMock(), MagicMock(), data)
    await mw(AsyncMock(), MagicMock(), data)   # второй раз — уже есть

    user = await session.get(User, 456)
    assert user is not None
    assert user.username == "x"