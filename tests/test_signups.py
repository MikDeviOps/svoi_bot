"""Тесты SignupService: capacity, дубликат, гонка, cancel, kick."""

from __future__ import annotations

import asyncio

import pytest

from app.errors import CapacityFull, Conflict, Forbidden, NotFound, PastEvent
from app.services.signups import SignupService


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


@pytest.mark.asyncio
async def test_join_race_capacity_one(session, make_user, make_event, db_engine):
    """Два параллельных join на capacity=1: ровно один успех.

    Внимание: это тест на ``SELECT ... FOR UPDATE``. При rollback
    транзакции (``session`` fixture) параллельные сессии не увидят
    незакоммиченные данные — поэтому гонку проверяем честно:
    два коммита через отдельные соединения.
    """
    owner = await make_user(tg_id=1)
    u1 = await make_user(tg_id=2)
    u2 = await make_user(tg_id=3)
    event = await make_event(owner.tg_id, capacity=1)

    # Commit, чтобы параллельные сессии видели event
    await session.commit()

    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async def attempt(user_id: int) -> bool:
        async with factory() as s:
            svc = SignupService(s)
            try:
                result = await svc.join(event.id, type("U", (), {"tg_id": user_id, "username": "", "full_name": "x"})())
                await s.commit()
                return result.joined
            except CapacityFull:
                await s.rollback()
                return False

    results = await asyncio.gather(attempt(u1.tg_id), attempt(u2.tg_id))
    assert sorted(results) == [False, True], "ровно один успех"

    # cleanup
    await session.execute(
        __import__("sqlalchemy").text("DELETE FROM signups")
    )
    await session.commit()


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