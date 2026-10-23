"""Тесты render_card: escape() и содержимое."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.config import get_settings
from app.services.notifications import render_card, render_summary


@pytest.mark.asyncio
async def test_render_card_escapes_html(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(
        owner.tg_id,
        title="<script>alert(1)</script>",
        description="<b>bold</b>",
    )

    text = render_card(event, booked=0, owner_name=owner.full_name, private_details=True)

    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "<b>bold</b>" not in text
    assert "&lt;b&gt;bold&lt;/b&gt;" in text


@pytest.mark.asyncio
async def test_render_card_contains_fields(session, make_user, make_event):
    owner = await make_user(tg_id=1, username="owner")
    event = await make_event(
        owner.tg_id,
        title="Test Event",
        description="Описание",
        capacity=5,
        source_chat_id=None,
    )

    text = render_card(event, booked=2, owner_name=owner.full_name, owner_username="owner")

    assert "Test Event" in text
    assert "Описание" in text
    assert "2/5" in text
    assert "Свободно: 3" in text
    assert "@owner" in text
    assert "Адрес" in text
    assert "Условия" in text


@pytest.mark.asyncio
async def test_render_card_private_false_hides_details(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, address="ул. Секретная, 1")

    text = render_card(event, booked=0, owner_name=owner.full_name, private_details=False)

    assert "ул. Секретная" not in text
    assert "🔒" in text


@pytest.mark.asyncio
async def test_render_summary(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    event = await make_event(owner.tg_id, title="Summary Test", capacity=3)

    text = render_summary(event, booked=1)

    assert "Summary Test" in text
    assert "1/3" in text