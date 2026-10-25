"""Smoke-тесты events: send_event_card кладёт EventMessage в БД."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.db import EventMessage
from app.routers.events import send_event_card


@pytest.mark.asyncio
async def test_send_event_card_saves_message(session, make_user, make_event):
    """``send_event_card`` → ``message.answer()`` → ``EventMessage`` в БД."""
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, capacity=5)

    # Фейковое сообщение: ``answer()`` — async, возвращает объект с chat.id / message_id
    fake_sent = MagicMock()
    fake_sent.chat = MagicMock(id=100)
    fake_sent.message_id = 55

    fake_message = MagicMock()
    fake_message.chat = MagicMock(id=100)
    fake_message.answer = AsyncMock(return_value=fake_sent)

    await send_event_card(fake_message, session, event, private_details=True)

    # Проверяем, что EventMessage записан
    result = await session.execute(
        select(EventMessage).where(EventMessage.event_id == event.id)
    )
    messages = list(result.scalars().all())

    assert len(messages) == 1
    assert messages[0].chat_id == 100
    assert messages[0].message_id == 55