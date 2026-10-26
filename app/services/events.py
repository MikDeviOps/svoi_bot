"""EventService — бизнес-правила для встреч.

Не знает про aiogram, keyboards, notifications. Работает через AsyncSession.
Все ошибки — доменные (app.errors).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import Event, Signup, User
from app.errors import Forbidden, NotFound, PastEvent, ValidationError
from app.schemas import EventDraft, EventView


async def _count_booked(session: AsyncSession, event_id: int) -> int:
    """Сколько записано на событие."""
    result = await session.scalar(
        select(func.count()).select_from(Signup).where(Signup.event_id == event_id)
    )
    return int(result or 0)


async def _get_or_raise(session: AsyncSession, event_id: int) -> Event:
    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        raise NotFound("Встреча не найдена.")
    return event


def _to_view(event: Event, booked: int, owner: User | None = None) -> EventView:
    owner_display = ""
    if owner is not None:
        owner_display = (
            f"{owner.full_name} (@{owner.username})"
            if owner.username
            else owner.full_name
        )
    return EventView(
        id=event.id,
        title=event.title,
        description=event.description,
        category=event.category,
        starts_at=event.starts_at,
        address=event.address,
        conditions=event.conditions,
        capacity=event.capacity,
        booked=booked,
        visibility=event.visibility,
        source_chat_id=event.source_chat_id,
        source_chat_title=event.source_chat_title,
        owner_id=event.owner_id,
        owner_display=owner_display,
    )


class EventService:
    """Сервис встреч. Не знает про keyboards/aiogram/notifications."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, draft: EventDraft, owner_id: int) -> EventView:
        settings = get_settings()
        required = (
            draft.title,
            draft.category,
            draft.event_date,
            draft.event_time,
            draft.address,
            draft.conditions,
            draft.capacity,
            draft.visibility,
        )
        if any(v is None for v in required):
            raise ValidationError("Заполнены не все поля встречи.")

        starts_at = datetime.combine(draft.event_date, draft.event_time).replace(
            tzinfo=settings.timezone
        )

        event = Event(
            owner_id=owner_id,
            title=draft.title,
            description=draft.description,
            category=draft.category,
            starts_at=starts_at,
            address=draft.address,
            conditions=draft.conditions,
            capacity=draft.capacity,
            visibility=draft.visibility,
            source_chat_id=draft.source_chat_id,
            source_chat_title=draft.source_chat_title,
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)

        owner = await self.session.get(User, owner_id)
        return _to_view(event, booked=0, owner=owner)

    async def update(
        self,
        event_id: int,
        actor_id: int,
        field: str,
        value,
    ) -> EventView:
        event = await _get_or_raise(self.session, event_id)
        if event.owner_id != actor_id:
            raise Forbidden("Редактировать встречу может только её создатель.")

        settings = get_settings()
        if field in {"title", "description", "address", "conditions", "category"}:
            setattr(event, field, value)
        elif field == "capacity":
            booked = await _count_booked(self.session, event_id)
            if not (booked <= int(value) <= settings.capacity_max):
                raise ValidationError(
                    f"Мест должно быть не меньше числа записанных ({booked}) "
                    f"и не больше {settings.capacity_max}."
                )
            event.capacity = int(value)
        elif field == "starts_at":
            if value <= datetime.now(settings.timezone):
                raise PastEvent("Встреча должна быть в будущем.")
            event.starts_at = value
        else:
            raise ValidationError(f"Неизвестное поле: {field}")

        event.updated_at = datetime.now(settings.timezone)
        await self.session.flush()
        booked = await _count_booked(self.session, event_id)
        owner = await self.session.get(User, event.owner_id)
        return _to_view(event, booked=booked, owner=owner)

    async def soft_delete(self, event_id: int, actor_id: int) -> None:
        event = await _get_or_raise(self.session, event_id)
        if event.owner_id != actor_id:
            raise Forbidden("Удалить встречу может только её создатель.")
        event.deleted_at = datetime.now(get_settings().timezone)
        await self.session.flush()

    async def get(self, event_id: int) -> EventView:
        event = await _get_or_raise(self.session, event_id)
        booked = await _count_booked(self.session, event_id)
        owner = await self.session.get(User, event.owner_id)
        return _to_view(event, booked=booked, owner=owner)

    async def list_by_owner(self, owner_id: int) -> list[EventView]:
        result = await self.session.execute(
            select(Event)
            .where(
                Event.owner_id == owner_id,
                Event.deleted_at.is_(None),
                Event.starts_at > datetime.now(get_settings().timezone),
            )
            .order_by(Event.starts_at)
            .limit(30)
        )
        events = list(result.scalars().all())
        owner = await self.session.get(User, owner_id)
        out: list[EventView] = []
        for event in events:
            booked = await _count_booked(self.session, event.id)
            out.append(_to_view(event, booked=booked, owner=owner))
        return out