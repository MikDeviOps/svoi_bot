"""SignupService — запись на встречу, отмена, удаление участника.

``join`` использует ``SELECT ... FOR UPDATE`` на ``events`` — защита
capacity от гонки (два параллельных join на capacity=1: ровно один успех).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import Event, Signup, User
from app.errors import CapacityFull, Conflict, Forbidden, NotFound, PastEvent
from app.schemas import CancelResult, JoinResult


async def _count_booked(session: AsyncSession, event_id: int) -> int:
    result = await session.scalar(
        select(func.count()).select_from(Signup).where(Signup.event_id == event_id)
    )
    return int(result or 0)


class SignupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def join(self, event_id: int, user: User) -> JoinResult:
        """Записать пользователя на встречу.

        Транзакция с ``SELECT ... FOR UPDATE`` на ``events``:
        - сериализует параллельные join;
        - capacity не превысится.
        """
        settings = get_settings()

        # SELECT ... FOR UPDATE на event
        result = await self.session.execute(
            select(Event).where(Event.id == event_id).with_for_update()
        )
        event = result.scalar_one_or_none()
        if event is None or event.deleted_at is not None:
            raise NotFound("Встреча не найдена.")

        if event.starts_at <= datetime.now(settings.timezone):
            raise PastEvent("Встреча уже началась или прошла.")

        # дубликат
        existing = await self.session.scalar(
            select(Signup).where(
                Signup.event_id == event_id, Signup.user_id == user.tg_id
            )
        )
        if existing is not None:
            booked = await _count_booked(self.session, event_id)
            return JoinResult(
                joined=False,
                reason=f"Вы уже записаны. Свободно мест: {max(0, event.capacity - booked)}.",
                available=max(0, event.capacity - booked),
            )

        booked = await _count_booked(self.session, event_id)
        if booked >= event.capacity:
            raise CapacityFull()

        signup = Signup(
            event_id=event_id,
            user_id=user.tg_id,
            telegram_name=(
                f"@{user.username}" if user.username else (user.full_name or "Имя не указано")
            )[:129],
        )
        self.session.add(signup)
        await self.session.flush()

        available = max(0, event.capacity - (booked + 1))
        return JoinResult(joined=True, available=available)

    async def cancel(self, event_id: int, user_id: int) -> CancelResult:
        signup = await self.session.scalar(
            select(Signup).where(
                Signup.event_id == event_id, Signup.user_id == user_id
            )
        )
        if signup is None:
            raise Conflict("Вы не записаны на эту встречу.")
        await self.session.delete(signup)
        await self.session.flush()

        event = await self.session.get(Event, event_id)
        booked = await _count_booked(self.session, event_id)
        available = max(0, event.capacity - booked) if event else 0
        return CancelResult(cancelled=True, available=available)

    async def kick(self, event_id: int, owner_id: int, target_user_id: int) -> None:
        event = await self.session.get(Event, event_id)
        if event is None or event.deleted_at is not None:
            raise NotFound("Встреча не найдена.")
        if event.owner_id != owner_id:
            raise Forbidden("Удалять участников может только организатор.")

        signup = await self.session.scalar(
            select(Signup).where(
                Signup.event_id == event_id, Signup.user_id == target_user_id
            )
        )
        if signup is None:
            raise Conflict("Участник уже не записан.")
        await self.session.delete(signup)
        await self.session.flush()

    async def list_participants(self, event_id: int) -> list[Signup]:
        result = await self.session.execute(
            select(Signup)
            .where(Signup.event_id == event_id)
            .order_by(Signup.created_at, Signup.user_id)
        )
        return list(result.scalars().all())