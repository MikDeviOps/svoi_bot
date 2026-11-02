"""Репозиторий для каталога участников."""
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ParticipantDirectory, Signup, Event
from app.db.base import utcnow


async def upsert_participant(session: AsyncSession, user_id: int, display_name: str, username: str) -> None:
    stmt = select(ParticipantDirectory).where(ParticipantDirectory.user_id == user_id)
    result = await session.execute(stmt)
    participant = result.scalar_one_or_none()

    if participant:
        participant.display_name = display_name
        participant.username = username
        participant.last_signup_at = utcnow()
    else:
        session.add(ParticipantDirectory(
            user_id=user_id,
            display_name=display_name,
            username=username,
            last_signup_at=utcnow(),
        ))


async def get_participants_page(session: AsyncSession, page: int = 0, page_size: int = 10) -> tuple[int, list[ParticipantDirectory]]:
    """Возвращает (total, список участников на странице)."""
    total_stmt = select(func.count(ParticipantDirectory.user_id))
    total = (await session.execute(total_stmt)).scalar() or 0

    stmt = (
        select(ParticipantDirectory)
        .order_by(ParticipantDirectory.last_signup_at.desc())
        .limit(page_size)
        .offset(page * page_size)
    )
    result = await session.execute(stmt)
    return total, list(result.scalars().all())


async def delete_participant(session: AsyncSession, user_id: int) -> bool:
    """Удаляет участника из каталога (не трогает его записи/встречи)."""
    stmt = delete(ParticipantDirectory).where(ParticipantDirectory.user_id == user_id)
    result = await session.execute(stmt)
    return result.rowcount > 0


async def find_participants_by_username(session: AsyncSession, username: str) -> list[ParticipantDirectory]:
    """Поиск по username (без учёта регистра благодаря CITEXT)."""
    clean = username.lstrip("@").lower()
    stmt = select(ParticipantDirectory).where(ParticipantDirectory.username == clean)
    result = await session.execute(stmt)
    return list(result.scalars().all())