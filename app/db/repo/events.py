"""Репозиторий для работы с встречами."""
from datetime import datetime
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Event, Signup

async def create_event(session: AsyncSession, **kwargs) -> Event:
    event = Event(**kwargs)
    session.add(event)
    await session.flush()
    return event

async def get_event(session: AsyncSession, event_id: int) -> Event | None:
    stmt = select(Event).where(Event.id == event_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def get_user_events(session: AsyncSession, user_id: int, upcoming_only: bool = True) -> list[Event]:
    stmt = select(Event).where(Event.owner_id == user_id)
    if upcoming_only:
        stmt = stmt.where(Event.starts_at > datetime.now()).order_by(Event.starts_at.asc())
    else:
        stmt = stmt.order_by(Event.starts_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()

async def delete_event(session: AsyncSession, event_id: int, owner_id: int | None = None) -> bool:
    stmt = delete(Event).where(Event.id == event_id)
    if owner_id is not None:
        stmt = stmt.where(Event.owner_id == owner_id)
    result = await session.execute(stmt)
    return result.rowcount > 0