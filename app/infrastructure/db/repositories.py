# app/infrastructure/db/repositories.py
from __future__ import annotations

from typing import Sequence

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    BlockedGroup,
    BlockedUser,
    Event,
    EventAttendance,
    EventExclusion,
    EventMessage,
    EventReview,
    GroupApplication,
    OrganizerStatReset,
    ParticipantDirectory,
    PendingUsernameBan,
    Signup,
)


class SQLAlchemyEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, event_id: int) -> Event | None:
        return await self.session.get(Event, event_id)

    async def get_with_booked_count(self, event_id: int) -> tuple[Event, int] | None:
        event = await self.session.get(Event, event_id)
        if event is None:
            return None
        stmt = (
            select(func.count())
            .select_from(Signup)
            .where(Signup.event_id == event_id)
        )
        result = await self.session.execute(stmt)
        booked = int(result.scalar_one())
        return event, booked

    async def create(self, event: Event) -> Event:
        self.session.add(event)
        await self.session.flush()
        return event

    async def delete(self, event_id: int) -> bool:
        """Удаляет встречу. CASCADE удаляет signups, event_messages,
        event_exclusions, event_attendance, event_reviews."""
        event = await self.session.get(Event, event_id)
        if event is None:
            return False
        await self.session.delete(event)
        await self.session.flush()
        return True

    async def count_by_owner(self, owner_id: int, *, after_id: int = 0) -> int:
        stmt = (
            select(func.count())
            .select_from(Event)
            .where(Event.owner_id == owner_id, Event.id > after_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_by_source_chat(self, source_chat_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Event)
            .where(Event.source_chat_id == source_chat_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_upcoming_by_owner(
        self,
        owner_id: int,
        *,
        after_id: int,
        today: str,
        clock: str,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Event)
            .where(
                Event.owner_id == owner_id,
                Event.id > after_id,
                (Event.date > today)
                | ((Event.date == today) & (Event.time > clock)),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_organizers(
        self,
        *,
        limit: int,
        offset: int,
        event_cutoff: int,
    ) -> Sequence[tuple[int, str, str, int]]:
        # (owner_id, name, username, total_events)
        stmt = (
            select(
                Event.owner_id,
                func.max(func.nullif(Event.owner_name, "")).label("name"),
                func.max(func.nullif(Event.owner_username, "")).label("username"),
                func.sum(
                    case((Event.id > event_cutoff, 1), else_=0)
                ).label("total"),
            )
            .group_by(Event.owner_id)
            .order_by(func.desc("total"), Event.owner_id)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return [
            (
                row.owner_id,
                row.name or "",
                row.username or "",
                int(row.total or 0),
            )
            for row in result
        ]

    async def count_organizers(self) -> int:
        stmt = select(func.count(func.distinct(Event.owner_id)))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class SQLAlchemySignupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, event_id: int, user_id: int) -> Signup | None:
        stmt = (
            select(Signup)
            .where(Signup.event_id == event_id, Signup.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_by_event(self, event_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Signup)
            .where(Signup.event_id == event_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_by_user(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Signup)
            .where(Signup.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_by_owner_after_cutoff(
        self,
        owner_id: int,
        *,
        signup_cutoff: int,
    ) -> int:
        # В PostgreSQL нет rowid; считаем все записи пользователя
        # на встречи этого владельца.
        stmt = (
            select(func.count())
            .select_from(Signup)
            .join(Event, Event.id == Signup.event_id)
            .where(Event.owner_id == owner_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_for_event(self, event_id: int) -> Sequence[Signup]:
        stmt = (
            select(Signup)
            .where(Signup.event_id == event_id)
            .order_by(Signup.created_at, Signup.user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_people_by_owner(
        self,
        owner_id: int,
        *,
        limit: int,
        offset: int,
    ) -> Sequence[tuple[int, str, str, int]]:
        stmt = (
            select(
                Signup.user_id,
                func.coalesce(
                    func.max(func.nullif(Signup.telegram_name, "")),
                    func.max(func.nullif(ParticipantDirectory.display_name, "")),
                    "Участник",
                ).label("name"),
                func.max(func.nullif(ParticipantDirectory.username, "")).label(
                    "username"
                ),
                func.count().label("signups_count"),
            )
            .join(Event, Event.id == Signup.event_id)
            .outerjoin(
                ParticipantDirectory,
                ParticipantDirectory.user_id == Signup.user_id,
            )
            .where(Event.owner_id == owner_id)
            .group_by(Signup.user_id)
            .order_by(func.desc("signups_count"), Signup.user_id)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return [
            (
                row.user_id,
                row.name or "Участник",
                row.username or "",
                int(row.signups_count),
            )
            for row in result
        ]

    async def count_people_by_owner(self, owner_id: int) -> int:
        stmt = (
            select(func.count(func.distinct(Signup.user_id)))
            .join(Event, Event.id == Signup.event_id)
            .where(Event.owner_id == owner_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def count_by_source_chat(self, source_chat_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Signup)
            .join(Event, Event.id == Signup.event_id)
            .where(Event.source_chat_id == source_chat_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def create(self, signup: Signup) -> None:
        self.session.add(signup)
        await self.session.flush()

    async def delete(self, event_id: int, user_id: int) -> bool:
        stmt = (
            delete(Signup)
            .where(Signup.event_id == event_id, Signup.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0


class SQLAlchemyParticipantDirectoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, participant: ParticipantDirectory) -> None:
        existing = await self.session.get(
            ParticipantDirectory, participant.user_id
        )
        if existing is None:
            self.session.add(participant)
        else:
            existing.display_name = participant.display_name
            existing.last_signup_at = participant.last_signup_at
            existing.username = participant.username
        await self.session.flush()

    async def get_by_user_id(self, user_id: int) -> ParticipantDirectory | None:
        return await self.session.get(ParticipantDirectory, user_id)


class SQLAlchemyReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, event_id: int, user_id: int) -> EventReview | None:
        stmt = (
            select(EventReview)
            .where(
                EventReview.event_id == event_id,
                EventReview.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, review: EventReview) -> None:
        existing = await self.get(review.event_id, review.user_id)
        if existing is None:
            self.session.add(review)
        else:
            existing.stars = review.stars
            existing.review = review.review
            existing.updated_at = review.updated_at
        await self.session.flush()

    async def delete(self, event_id: int, user_id: int) -> bool:
        stmt = (
            delete(EventReview)
            .where(
                EventReview.event_id == event_id,
                EventReview.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def list_by_event(
        self,
        event_id: int,
        *,
        limit: int,
    ) -> Sequence[EventReview]:
        stmt = (
            select(EventReview)
            .where(EventReview.event_id == event_id)
            .order_by(EventReview.updated_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_stats(self, event_id: int) -> tuple[int, float | None]:
        stmt = select(
            func.count(), func.avg(EventReview.stars)
        ).where(EventReview.event_id == event_id)
        result = await self.session.execute(stmt)
        row = result.one()
        return int(row[0]), (float(row[1]) if row[1] is not None else None)


class SQLAlchemySecurityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_user_blocked(self, user_id: int) -> bool:
        stmt = select(BlockedUser.user_id).where(BlockedUser.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.first() is not None

    async def is_group_blocked(self, chat_id: int) -> bool:
        stmt = select(BlockedGroup.chat_id).where(
            BlockedGroup.chat_id == chat_id
        )
        result = await self.session.execute(stmt)
        return result.first() is not None

    async def is_excluded(self, event_id: int, user_id: int) -> bool:
        stmt = select(EventExclusion.user_id).where(
            EventExclusion.event_id == event_id,
            EventExclusion.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.first() is not None

    async def get_group_application_status(self, chat_id: int) -> str | None:
        stmt = select(GroupApplication.status).where(
            GroupApplication.chat_id == chat_id
        )
        result = await self.session.execute(stmt)
        row = result.first()
        return row[0] if row else None

    async def resolve_pending_username_ban(
        self,
        user_id: int,
        username: str,
    ) -> bool:
        stmt = select(PendingUsernameBan).where(
            PendingUsernameBan.username == username,
            PendingUsernameBan.resolved_user_id.is_(None),
        )
        result = await self.session.execute(stmt)
        pending = result.scalar_one_or_none()
        if pending is None:
            return False
        existing_block = await self.session.get(BlockedUser, user_id)
        if existing_block is None:
            self.session.add(
                BlockedUser(
                    user_id=user_id,
                    reason="Блокировка по нику",
                    blocked_at=pending.blocked_at,
                    blocked_by=pending.blocked_by,
                )
            )
        pending.resolved_user_id = user_id
        await self.session.flush()
        return True

    async def block_user(
        self,
        user_id: int,
        *,
        reason: str,
        blocked_by: int,
        blocked_at: str,
    ) -> None:
        existing = await self.session.get(BlockedUser, user_id)
        if existing is None:
            self.session.add(
                BlockedUser(
                    user_id=user_id,
                    reason=reason,
                    blocked_at=blocked_at,
                    blocked_by=blocked_by,
                )
            )
            await self.session.flush()

    async def get_owner_stat_reset(
        self, owner_id: int
    ) -> tuple[int, int] | None:
        reset = await self.session.get(OrganizerStatReset, owner_id)
        if reset is None:
            return None
        return reset.event_cutoff, reset.signup_cutoff


class SQLAlchemyEventMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_event(self, event_id: int) -> Sequence[EventMessage]:
        stmt = select(EventMessage).where(EventMessage.event_id == event_id)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def save(self, message: EventMessage) -> None:
        self.session.add(message)
        await self.session.flush()


class SQLAlchemyEventExclusionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, exclusion: EventExclusion) -> None:
        self.session.add(exclusion)
        await self.session.flush()

    async def remove(self, event_id: int, user_id: int) -> bool:
        stmt = (
            delete(EventExclusion)
            .where(
                EventExclusion.event_id == event_id,
                EventExclusion.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    async def is_excluded(self, event_id: int, user_id: int) -> bool:
        stmt = select(EventExclusion.user_id).where(
            EventExclusion.event_id == event_id,
            EventExclusion.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        return result.first() is not None

    async def list_by_event(self, event_id: int) -> Sequence[EventExclusion]:
        stmt = (
            select(EventExclusion)
            .where(EventExclusion.event_id == event_id)
            .order_by(EventExclusion.excluded_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class SQLAlchemyEventAttendanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_attended(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(EventAttendance)
            .where(
                EventAttendance.user_id == user_id,
                EventAttendance.attended.is_(True),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def get(
        self, event_id: int, user_id: int
    ) -> EventAttendance | None:
        stmt = (
            select(EventAttendance)
            .where(
                EventAttendance.event_id == event_id,
                EventAttendance.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()