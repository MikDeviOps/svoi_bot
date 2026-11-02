"""Репозиторий для статистики и обнуления счётчиков."""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, Signup, OrganizerStatReset, EventAttendance, ParticipantDirectory
from app.db.base import utcnow


async def get_platform_stats(session: AsyncSession) -> dict:
    """Общая статистика платформы."""
    total_events = await session.execute(select(func.count(Event.id)))
    total_signups = await session.execute(select(func.count(Signup.id)))
    total_participants = await session.execute(select(func.count(ParticipantDirectory.user_id)))

    return {
        "total_events": total_events.scalar() or 0,
        "total_signups": total_signups.scalar() or 0,
        "total_participants": total_participants.scalar() or 0,
    }


async def get_organizer_stats(session: AsyncSession, owner_id: int) -> dict:
    """Статистика конкретного организатора."""
    total = await session.execute(select(func.count(Event.id)).where(Event.owner_id == owner_id))
    signed = await session.execute(
        select(func.count(Signup.id)).select_from(Signup).join(Event).where(Event.owner_id == owner_id)
    )
    attended = await session.execute(
        select(func.count(EventAttendance.user_id)).where(
            EventAttendance.user_id == owner_id,
            EventAttendance.attended == True,
        )
    )

    return {
        "total_events": total.scalar() or 0,
        "total_signups": signed.scalar() or 0,
        "total_attended": attended.scalar() or 0,
    }


async def get_stat_reset(session: AsyncSession, owner_id: int) -> OrganizerStatReset | None:
    stmt = select(OrganizerStatReset).where(OrganizerStatReset.owner_id == owner_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def set_stat_reset(
    session: AsyncSession,
    owner_id: int,
    event_cutoff: int,
    signup_cutoff: int,
) -> None:
    reset = await get_stat_reset(session, owner_id)
    if reset:
        reset.event_cutoff = event_cutoff
        reset.signup_cutoff = signup_cutoff
        reset.reset_at = utcnow()
    else:
        session.add(OrganizerStatReset(
            owner_id=owner_id,
            event_cutoff=event_cutoff,
            signup_cutoff=signup_cutoff,
            reset_at=utcnow(),
        ))


async def get_max_event_id(session: AsyncSession, owner_id: int) -> int:
    stmt = select(func.max(Event.id)).where(Event.owner_id == owner_id)
    result = await session.execute(stmt)
    return result.scalar() or 0


async def get_max_signup_id(session: AsyncSession, owner_id: int) -> int:
    stmt = (
        select(func.max(Signup.id))
        .select_from(Signup)
        .join(Event)
        .where(Event.owner_id == owner_id)
    )
    result = await session.execute(stmt)
    return result.scalar() or 0