"""Репозиторий для работы с отзывами на встречи."""
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventReview
from app.db.base import utcnow


async def create_review(
    session: AsyncSession,
    event_id: int,
    user_id: int,
    stars: int,
    review: str,
    event_title: str,
    organizer_id: int,
) -> EventReview:
    now = utcnow()
    new_review = EventReview(
        event_id=event_id,
        user_id=user_id,
        stars=stars,
        review=review,
        event_title=event_title,
        organizer_id=organizer_id,
        created_at=now,
        updated_at=now,
    )
    session.add(new_review)
    await session.flush()
    return new_review


async def get_event_reviews(session: AsyncSession, event_id: int) -> list[EventReview]:
    stmt = (
        select(EventReview)
        .where(EventReview.event_id == event_id)
        .order_by(EventReview.created_at.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_user_reviews(session: AsyncSession, user_id: int, limit: int = 50) -> list[EventReview]:
    stmt = (
        select(EventReview)
        .where(EventReview.user_id == user_id)
        .order_by(EventReview.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_organizer_reviews(session: AsyncSession, organizer_id: int, limit: int = 50) -> list[EventReview]:
    stmt = (
        select(EventReview)
        .where(EventReview.organizer_id == organizer_id)
        .order_by(EventReview.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def delete_review(session: AsyncSession, event_id: int, user_id: int) -> bool:
    stmt = delete(EventReview).where(
        EventReview.event_id == event_id,
        EventReview.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.rowcount > 0


async def get_average_rating(session: AsyncSession, organizer_id: int) -> float | None:
    stmt = select(func.avg(EventReview.stars)).where(EventReview.organizer_id == organizer_id)
    result = await session.execute(stmt)
    return result.scalar()