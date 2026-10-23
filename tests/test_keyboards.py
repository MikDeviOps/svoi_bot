"""Тесты event_kb: владелец/гость, capacity=0."""

from __future__ import annotations

import pytest

from app.keyboards import event_kb


@pytest.mark.asyncio
async def test_event_kb_owner_sees_delete(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, capacity=5)

    kb = event_kb(event, booked=0, viewer_id=owner.tg_id)

    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert any(cb and cb.startswith("deleteask:") for cb in callbacks)


@pytest.mark.asyncio
async def test_event_kb_guest_no_delete(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, capacity=5)

    kb = event_kb(event, booked=0, viewer_id=999)

    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert not any(cb and cb.startswith("deleteask:") for cb in callbacks)


@pytest.mark.asyncio
async def test_event_kb_full(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, capacity=1)

    kb = event_kb(event, booked=1)

    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Мест нет" in labels
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert any(cb and cb.startswith("full:") for cb in callbacks)


@pytest.mark.asyncio
async def test_event_kb_join(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, capacity=5)

    kb = event_kb(event, booked=0)

    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "Записаться" in labels