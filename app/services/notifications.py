"""Рендер карточек и refresh сообщений в чатах.

- render_card — escape() на всех пользовательских полях.
- CATEGORY_LABELS — из app/labels.py (разрыв circular import).
- _refresh — try/except TelegramBadRequest (message is not modified — skip).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from html import escape

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Event, EventMessage, User
from app.labels import CATEGORY_LABELS
from app.services.events import _count_booked

logger = structlog.get_logger(__name__)

_REFRESH_LOCKS: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _format_datetime(event: Event) -> str:
    dt = event.starts_at
    return f"{dt.strftime('%d.%m.%Y')} · {dt.strftime('%H:%M')} (МСК)"


def _owner_display(event: Event, owner_name: str = "", owner_username: str = "") -> str:
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
    available = max(0, event.capacity - booked)
    category = CATEGORY_LABELS.get(event.category, "🎭 Другое")
    return (
        f"📍 <b>{escape(event.title)}</b>\n"
        f"🕒 {event.starts_at.strftime('%H:%M')} · {category}\n"
        f"👥 {booked}/{event.capacity} · Свободно: {available}"
    )


async def _refresh(event_id: int, session: AsyncSession, bot: Bot) -> None:
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
            event, booked,
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
            except TelegramBadRequest as exc:
                err = str(exc)
                if "message is not modified" in err:
                    continue
                if "message to edit not found" in err:
                    continue
                logger.info(
                    "refresh_failed",
                    event_id=event_id,
                    chat_id=msg.chat_id,
                    message_id=msg.message_id,
                    error=err,
                )


async def enqueue_refresh(event_id: int, session: AsyncSession, bot: Bot) -> None:
    await _refresh(event_id, session, bot)