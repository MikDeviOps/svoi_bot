"""Тесты AgendaService: dates, categories, page, scope-фильтр."""

from __future__ import annotations

import pytest

from app.services.agenda import AgendaService


@pytest.mark.asyncio
async def test_dates_public(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    await make_event(owner.tg_id, visibility="public", starts_in_days=1)
    await make_event(owner.tg_id, visibility="public", starts_in_days=1)
    await make_event(owner.tg_id, visibility="public", starts_in_days=3)

    svc = AgendaService(session)
    page = await svc.dates(("public", None))

    # 2 уникальные даты (сегодня+1, сегодня+3)
    assert len(page.dates) == 2


@pytest.mark.asyncio
async def test_dates_chat_scope_isolated(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    await make_event(
        owner.tg_id, visibility="chat", source_chat_id=-100
    )
    await make_event(
        owner.tg_id, visibility="chat", source_chat_id=-200
    )

    svc = AgendaService(session)
    page = await svc.dates(("chat", -100))
    assert len(page.dates) == 1


@pytest.mark.asyncio
async def test_categories_count(session, make_user, make_event):
    from datetime import datetime, timedelta
    from app.config import get_settings

    owner = await make_user(tg_id=1)
    tomorrow = (
        datetime.now(get_settings().timezone) + timedelta(days=1)
    ).date()

    await make_event(owner.tg_id, category="games", starts_in_days=1)
    await make_event(owner.tg_id, category="games", starts_in_days=1)
    await make_event(owner.tg_id, category="bars", starts_in_days=1)

    svc = AgendaService(session)
    page = await svc.categories(("public", None), tomorrow)

    assert page.categories.get("games") == 2
    assert page.categories.get("bars") == 1


@pytest.mark.asyncio
async def test_page_pagination(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    for _ in range(15):
        await make_event(owner.tg_id, category="games", starts_in_days=1)

    from datetime import datetime, timedelta
    from app.config import get_settings

    tomorrow = (
        datetime.now(get_settings().timezone) + timedelta(days=1)
    ).date()

    svc = AgendaService(session)
    p0 = await svc.page(("public", None), tomorrow, "games", page=0)
    p1 = await svc.page(("public", None), tomorrow, "games", page=1)

    assert len(p0) == 10
   