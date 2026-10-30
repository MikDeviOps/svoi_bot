"""SignupService — бизнес-правила записи на встречу.

Не знает про aiogram. Работает через AsyncSession.
Все ошибки — доменные (app.errors).

Гонки:
- ``join`` берёт ``SELECT ... FOR UPDATE`` на строку ``events`` — параллельные
  запросы сериализуются, capacity не превышается.
- ``cancel`` идемпотентен: повторный клик не падает.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import Event, Signup, User
from app.errors import (
    CapacityFull,
    Conflict,
    DomainError,
    Forbidden,
    NotFound,
    PastEvent,
    ValidationError,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class JoinResult:
    """Результат записи — для рендера ответа и уведомления группы."""
    booked: int
    user_message: str
    joined: bool


@dataclass(frozen=True)
class CancelResult:
    """Результат отмены — для рендера ответа и уведомления группы."""
    booked: int
    user_message: str
    cancelled: bool


async def _count_booked(session: AsyncSession, event_id: int) -> int:
    result = await session.scalar(
        select(func.count()).select_from(Signup).where(Signup.event_id == event_id)
    )
    return int(result or 0)


class SignupService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    async def join(self, event_id: int, user) -> JoinResult:
        """Записать пользователя. ``user`` — aiogram User или ORM User.

        Возвращает ``JoinResult`` с актуальным ``booked`` и готовым текстом.
        Если уже записан — ``joined=False`` и сообщение «вы уже записаны».
        """
        settings = get_settings()
        tg_id = int(getattr(user, "id", user))
        username = (getattr(user, "username", "") or "")[:64]
        full_name = (getattr(user, "full_name", "") or "")[:255]

        # Upsert пользователя в справочник — до транзакции записи.
        await self._upsert_user(tg_id, username, full_name)

        # Блокируем строку события — сериализует параллельные join.
        result = await self.session.execute(
            select(Event).where(Event.id == event_id).with_for_update()
        )
        event = result.scalar_one_or_none()
        if event is None or event.deleted_at is not None:
            raise NotFound("Встреча не найдена.")
        if event.starts_at <= datetime.now(settings.timezone):
            raise PastEvent("Встреча уже началась или прошла.")

        # Уже записан? Идемпотентно.
        existing = await self.session.get(Signup, (event_id, tg_id))
        if existing is not None:
            booked = await _count_booked(self.session, event_id)
            return JoinResult(
                booked=booked,
                joined=False,
                user_message=(
                    f"Вы уже записаны на встречу «{event.title}». "
                    f"Свободно мест: {max(0, event.capacity - booked)}."
                ),
            )

        booked = await _count_booked(self.session, event_id)
        if booked >= event.capacity:
            raise CapacityFull(
                f"К сожалению, свободных мест уже нет. "
                f"Записано: {booked}/{event.capacity}."
            )

        telegram_name = (
            f"@{username}" if username else (full_name or str(tg_id))
        )[:129]
        self.session.add(Signup(
            event_id=event_id,
            user_id=tg_id,
            telegram_name=telegram_name,
        ))
        await self.session.flush()
        booked = await _count_booked(self.session, event_id)
        return JoinResult(
            booked=booked,
            joined=True,
            user_message=(
                f"Вы записаны на встречу «{event.title}»!\n"
                f"📅 {event.starts_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"🏠 {event.address}\n"
                f"📋 {event.conditions}\n"
                f"Свободно мест: {max(0, event.capacity - booked)}."
            ),
        )

    # ------------------------------------------------------------------
    # Отмена
    # ------------------------------------------------------------------

    async def cancel(self, event_id: int, user_id: int) -> CancelResult:
        """Отменить запись. Идемпотентно: если не записан — сообщение без ошибки."""
        settings = get_settings()
        result = await self.session.execute(
            select(Event).where(Event.id == event_id).with_for_update()
        )
        event = result.scalar_one_or_none()
        if event is None or event.deleted_at is not None:
            raise NotFound("Встреча не найдена.")
        if event.starts_at <= datetime.now(settings.timezone):
            raise PastEvent("Встреча уже началась — отменить запись нельзя.")

        existing = await self.session.get(Signup, (event_id, user_id))
        if existing is None:
            booked = await _count_booked(self.session, event_id)
            return CancelResult(
                booked=booked,
                cancelled=False,
                user_message="Вы не записаны на эту встречу.",
            )

        await self.session.delete(existing)
        await self.session.flush()
        booked = await _count_booked(self.session, event_id)
        return CancelResult(
            booked=booked,
            cancelled=True,
            user_message=(
                f"Запись на встречу «{event.title}» отменена. "
                f"Свободно мест: {max(0, event.capacity - booked)}."
            ),
        )

    # ------------------------------------------------------------------
    # Управление организатором
    # ------------------------------------------------------------------

    async def list_participants(self, event_id: int) -> list[Signup]:
        """Список записанных — по времени записи, затем по user_id."""
        result = await self.session.execute(
            select(Signup)
            .where(Signup.event_id == event_id)
            .order_by(Signup.created_at, Signup.user_id)
        )
        return list(result.scalars().all())

    async def kick(self, event_id: int, actor_id: int, target_user_id: int) -> None:
        """Удалить участника. Только владелец встречи."""
        event = await self.session.get(Event, event_id)
        if event is None or event.deleted_at is not None:
            raise NotFound("Встреча не найдена.")
        if event.owner_id != actor_id:
            raise Forbidden("Это не ваша встреча.")

        existing = await self.session.get(Signup, (event_id, target_user_id))
        if existing is None:
            raise NotFound("Участник уже не записан.")
        await self.session.delete(existing)
        await self.session.flush()

    # ------------------------------------------------------------------
    # Вспомогательное
    # ------------------------------------------------------------------

    async def _upsert_user(self, tg_id: int, username: str, full_name: str) -> None:
        """Обновить username/full_name в справочнике users (не трогая created_at)."""
        existing = await self.session.get(User, tg_id)
        if existing is None:
            self.session.add(User(tg_id=tg_id, username=username, full_name=full_name))
        else:
            existing.username = username
            existing.full_name = full_name
        await self.session.flush()