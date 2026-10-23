"""Тесты can_access_event и ensure_owner."""

from __future__ import annotations

import pytest

from app.errors import Forbidden
from app.services.permissions import can_access_event, ensure_owner


class _Member:
    def __init__(self, status: str, is_member: bool | None = None) -> None:
        self.status = status
        self.is_member = is_member


class FakeBot:
    def __init__(self, members: dict[tuple[int, int], _Member | None]) -> None:
        self._members = members

    async def get_chat_member(self, chat_id: int, user_id: int):
        return self._members.get((chat_id, user_id))


@pytest.mark.asyncio
async def test_public_event_accessible_to_all(make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, visibility="public")
    bot = FakeBot({})
    assert await can_access_event(
        event, chat_id=None, chat_type=None, user_id=999, bot=bot
    )


@pytest.mark.asyncio
async def test_chat_event_visible_in_source_chat(make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, visibility="chat", source_chat_id=-100)
    bot = FakeBot({})
    assert await can_access_event(
        event, chat_id=-100, chat_type="group", user_id=999, bot=bot
    )


@pytest.mark.asyncio
async def test_chat_event_hidden_for_outsider(make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, visibility="chat", source_chat_id=-100)
    bot = FakeBot({})  # не член
    assert not await can_access_event(
        event, chat_id=None, chat_type=None, user_id=999, bot=bot
    )


@pytest.mark.asyncio
async def test_chat_event_visible_for_member(make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, visibility="chat", source_chat_id=-100)
    bot = FakeBot({(-100, 999): _Member("member")})
    assert await can_access_event(
        event, chat_id=None, chat_type=None, user_id=999, bot=bot
    )


@pytest.mark.asyncio
async def test_chat_event_no_source_chat(make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, visibility="chat", source_chat_id=None)
    bot = FakeBot({})
    assert not await can_access_event(
        event, chat_id=None, chat_type=None, user_id=999, bot=bot
    )


def test_ensure_owner_raises_for_other():
    class E:
        owner_id = 1

    with pytest.raises(Forbidden):
        ensure_owner(E(), actor_id=2)


def test_ensure_owner_ok():
    class E:
        owner_id = 1

    ensure_owner(E(), actor_id=1)