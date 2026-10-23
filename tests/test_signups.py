"""Тесты SignupService: capacity, дубликат, гонка, cancel, kick."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.db import Event, User
from app.errors import CapacityFull, Conflict, Forbidden, NotFound, PastEvent
from app.services.signups import SignupService


# ---------------------------------------------------------------------------
# Базовые сценарии
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_ok(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    guest = await make_user(tg_id=2)
    event = await make_event(owner.tg_id, capacity=2)

    svc = SignupService(session)
    result = await svc.join(event.id, guest)

    assert result.joined is True
    assert result.available == 1


@pytest.mark.asyncio
async def test_join_duplicate_returns_not_joined(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    guest = await make_user(tg_id=2)
    event = await make_event(owner.tg_id, capacity=5)

    svc = SignupService(session)
    await svc.join(event.id, guest)
    result = await svc.join(event.id, guest)

    assert result.joined is False
    assert "уже записаны" in result.reason


@pytest.mark.asyncio
async def test_join_capacity_full(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    e1 = await make_user(tg_id=2)
    e2 = await make_user(tg_id=3)
    event = await make_event(owner.tg_id, capacity=1)

    svc = SignupService(session)
    await svc.join(event.id, e1)

    with pytest.raises(CapacityFull):
        await svc.join(event.id, e2)


@pytest.mark.asyncio
async def test_join_past_event(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    guest = await make_user(tg_id=2)
    event = await make_event(owner.tg_id, starts_in_days=-1)

    svc = SignupService(session)
    with pytest.raises(PastEvent):
        await svc.join(event.id, guest)


@pytest.mark.asyncio
async def test_join_not_found(session, make_user):
    guest = await make_user(tg_id=2)
    svc = SignupService(session)
    with pytest.raises(NotFound):
        await svc.join(9999, guest)


# ---------------------------------------------------------------------------
# Гонка
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_join_race_capacity_one(make_user, make_event, db_engine, session):
    """Два параллельных join на capacity=1: ровно один успех.

    ``session``-фикстура делает rollback после теста — значит, нельзя
    опираться на её данные в параллельных сессиях. Поэтому создаём данные
    в **отдельной** сессии из ``db_engine`` с явным ``commit()``.

    ``SELECT ... FOR UPDATE`` в ``SignupService.join`` сериализует
    параллельные join: одна транзакция ждёт другую, вторая видит уже
    заполненный capacity и падает в ``CapacityFull``.
    """
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    # --- setup: отдельная сессия + commit ---
    async with factory() as setup_session:
        owner = User(tg_id=101, username="owner", full_name="Owner")
        u1 = User(tg_id=102, username="u1", full_name="User 1")
        u2 = User(tg_id=103, username="u2", full_name="User 2")
        setup_session.add_all([owner, u1, u2])
        await setup_session.flush()

        event = Event(
            owner_id=owner.tg_id,
            title="Race Event",
            description="",
            category="games",
            starts_at=datetime.now(get_settings().timezone) + timedelta(days=1),
            address="ул. Тестовая, 1",
            conditions="бесплатно",
            capacity=1,
            visibility="public",
            source_chat_id=None,
            source_chat_title="",
        )
        setup_session.add(event)
        await setup_session.commit()
        event_id = event.id
        u1_id = u1.tg_id
        u2_id = u2.tg_id

    # --- race: два параллельных join через отдельные сессии ---
    async def attempt(user_id: int) -> bool:
        async with factory() as s:
            svc = SignupService(s)
            try:
                result = await svc.join(
                    event_id,
                    type("U", (), {
                        "tg_id": user_id, "username": "", "full_name": "x",
                    })(),
                )
                await s.commit()
                return result.joined
            except CapacityFull:
                await s.rollback()
                return False

    try:
        results = await asyncio.gather(attempt(u1_id), attempt(u2_id))
        assert sorted(results) == [False, True], "ровно один успех"
    finally:
        # --- cleanup: чистим всё, что создали ---
        async with db_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM signups WHERE event_id = :eid"), {"eid": event_id}
            )
            await conn.execute(
                text("DELETE FROM events WHERE id = :eid"), {"eid": event_id}
            )
            await conn.execute(
                text("DELETE FROM users WHERE tg_id IN (101, 102, 103)")
            )


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    guest = await make_user(tg_id=2)
    event = await make_event(owner.tg_id, capacity=5)

    svc = SignupService(session)
    await svc.join(event.id, guest)
    result = await svc.cancel(event.id, guest.tg_id)

    assert result.cancelled is True
    assert result.available == 5


@pytest.mark.asyncio
async def test_cancel_not_signed(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    guest = await make_user(tg_id=2)
    event = await make_event(owner.tg_id)

    svc = SignupService(session)
    with pytest.raises(Conflict):
        await svc.cancel(event.id, guest.tg_id)


# ---------------------------------------------------------------------------
# Kick
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kick_ok(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    guest = await make_user(tg_id=2)
    event = await make_event(owner.tg_id, capacity=5)

    svc = SignupService(session)
    await svc.join(event.id, guest)
    await svc.kick(event.id, owner.tg_id, guest.tg_id)

    parts = await svc.list_participants(event.id)
    assert parts == []


@pytest.mark.asyncio
async def test_kick_forbidden(session, make_user, make_event):
    owner = await make_user(tg_id=1)
    guest = await make_user(tg_id=2)
    event = await make_event(owner.tg_id)

    svc = SignupService(session)
    with pytest.raises(Forbidden):
        await svc.kick(event.id, guest.tg_id, owner.tg_id)