"""Рендер карточек и refresh сообщений в чатах.

Единственное место с ``escape()``: любые пользовательские данные
(title, description, address, conditions, имена) попадают в HTML
только после экранирования.

``enqueue_refresh`` сейчас вызывает ``_refresh`` напрямую. Позже
(сценарий C) тело заменится на ``redis.xadd`` — сигнатура не меняется,
роутеры не трогаем.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from html import escape

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.db import Event
from app.services.events import _count_booked
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


CATEGORY_LABELS: dict[str, str] = {
    "games": "🎲 Игры",
    "bars": "🍺 Бары",
    "restaurants": "🍽️ Рестораны",
    "clubs": "💃 Клубы",
    "concerts": "🎤 Концерты",
    "outdoors": "🌳 Пикники и природа",
    "houses": "🏡 Отдых в доме",
    "parties": "🎉 Вечеринки",
    "other": "🎭 Другое",
}

# Per-event lock: два параллельных refresh на одно event_id ждут друг друга.
_REFRESH_LOCKS: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _format_datetime(event: Event) -> str:
    """``dd.mm.yyyy · HH:MM (МСК)``."""
    dt = event.starts_at
    return f"{dt.strftime('%d.%m.%Y')} · {dt.strftime('%H:%M')} (МСК)"


def _owner_display(event: Event, owner_name: str | None = None, owner_username: str | None = None) -> str:
    if owner_username:
        return f"@{owner_username}"
    if owner_name:
        return owner_name
    return "организатор"


def render_card(
    event: Event,
    booked: int,
    *,
    owner_name: str = "",
    owner_username: str = "",
    private_details: bool = True,
) -> str:
    """HTML-карточка события.

    Все пользовательские поля — через ``escape()``.
    """
    available = max(0, event.capacity - booked)
    category = CATEGORY_LABELS.get(event.category, "🎭 Другое")

    lines = [
        f"📍 <b>{escape(event.title)}</b>",
        f"📅 {_format_datetime(event)}",
        f"Категория: {category}",
        f"👥 Участники: {booked}/{event.capacity} · Свободно: {available}",
    ]
    if event.description:
        lines.append(f"📝 Описание: {escape(event.description)}")

    organizer = _owner_display(event, owner_name, owner_username)
    lines.append(f"👤 Организатор: {escape(organizer)}")

    if event.source_chat_title:
        lines.append(f"🏘 Группа: {escape(event.source_chat_title)}")

    if private_details:
        lines.append(f"🏠 Адрес: {escape(event.address)}")
        lines.append(f"📋 Условия: {escape(event.conditions)}")
    else:
        lines.append("🔒 Точный адрес и условия доступны в личном чате с ботом.")

    return "\n".join(lines)


def render_summary(event: Event, booked: int) -> str:
    """Короткая сводка (для «мои встречи», списков)."""
    available = max(0, event.capacity - booked)
    category = CATEGORY_LABELS.get(event.category, "🎭 Другое")
    return (
        f"📍 <b>{escape(event.title)}</b>\n"
        f"🕒 {event.starts_at.strftime('%H:%M')} · {category}\n"
        f"👥 {booked}/{event.capacity} · Свободно: {available}"
    )


async def _refresh(event_id: int, session: AsyncSession, bot: Bot) -> None:
    """Обновить все известные карточки события. Под per-event lock."""
    from sqlalchemy import select
    from app.db import EventMessage, User

    lock = _REFRESH_LOCKS[event_id]
    async with lock:
        event = await session.get(Event, event_id)
        if event is None or event.deleted_at is not None:
            return

        booked = await _count_booked(session, event_id)
        owner = await session.get(User, event.owner_id)
        owner_name = owner.full_name if owner else ""
        owner_username = owner.username if owner else ""

        text = render_card(
            event,
            booked,
            owner_name=owner_name,
            owner_username=owner_username,
            private_details=True,
        )

        result = await session.execute(
            select(EventMessage).where(EventMessage.event_id == event_id)
        )
        messages = list(result.scalars().all())
        for msg in messages:
            try:
                await bot.edit_message_text(
                    chat_id=msg.chat_id,
                    message_id=msg.message_id,
                    text=text,
                    parse_mode="HTML",
                )
            except TelegramAPIError as exc:
                logger.info(
                    "refresh_failed",
                    event_id=event_id,
                    chat_id=msg.chat_id,
                    message_id=msg.message_id,
                    error=str(exc),
                )


async def enqueue_refresh(event_id: int, session: AsyncSession, bot: Bot) -> None:
    """Точка входа для refresh. Сейчас — прямой вызов.

    Позже заменим на ``redis.xadd`` без изменения сигнатуры.
    """
    await _refresh(event_id, session, bot)