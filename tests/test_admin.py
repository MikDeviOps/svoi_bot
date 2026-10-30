"""Тесты /stats: owner only, считает users/events/signups."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers.admin import stats
from app.services.events import EventService


class _FakeFromUser:
    def __init__(self, user_id: int):
        self.id = user_id


class _FakeMessage:
    def __init__(self, user_id: int):
        self.from_user = _FakeFromUser(user_id)
        self.answer = AsyncMock()


@pytest.mark.asyncio
async def test_stats_owner(session, make_user, make_event, monkeypatch):
    # owner_id = 42 в Settings
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "owner_id", 42, raising=False)

    owner = await make_user(tg_id=42)
    event = await make_event(owner.tg_id)

    message = _FakeMessage(user_id=42)
    await stats(message, session)

    text = message.answer.call_args.args[0]
    assert "СВОИ" in text
    assert "1" in text  # users
    assert "Встреч" in text


@pytest.mark.asyncio
async def test_stats_non_owner(session, make_user, monkeypatch):
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "owner_id", 42, raising=False)

    await make_user(tg_id=99)

    message = _FakeMessage(user_id=99)
    await stats(message, session)

    text = message.answer.call_args.args[0]
    assert "владельцу" in text