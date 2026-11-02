"""Репозиторий для работы с записями на встречи."""
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Signup, Event

async def add_signup(session: AsyncSession, event_id: int, user_id: int, telegram_name: str) -> bool:
    # Проверка на дубликат и вместимость в одной транзакции
    stmt = select(Event.capacity, func.count(Signup.id)).select_from(Event).outerjoin(
        Signup, Event.id == Signup.event_id
    ).where(Event.id == event_id).group_by(Event.id).with_for_update()
    
    result = await session.execute(stmt)
    row = result.fetchone()
    if not row:
        return False
        
    capacity, current_count = row
    if current_count >= capacity:
        return False
        
    # Проверка, не записан ли уже
    exists = await session.execute(
        select(Signup.id).where(Signup.event_id == event_id, Signup.user_id == user_id)
    )
    if exists.scalar_one_or_none():
        return False

    new_signup = Signup(event_id=event_id, user_id=user_id, telegram_name=telegram_name)
    session.add(new_signup)
    return True

async def remove_signup(session: AsyncSession, event_id: int, user_id: int) -> bool:
    stmt = delete(Signup).where(Signup.event_id == event_id, Signup.user_id == user_id)
    result = await session.execute(stmt)
    return result.rowcount > 0

async def get_event_signups(session: AsyncSession, event_id: int) -> list[Signup]:
    stmt = select(Signup).where(Signup.event_id == event_id).order_by(Signup.created_at.asc())
    result = await session.execute(stmt)
    return result.scalars().all()