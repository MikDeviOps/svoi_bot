"""Сервисный слой встреч: счётчики, текст карточки, обновление и архивация сообщений."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import utcnow
from app.db.models import Event, EventMessage, Signup
from app.keyboards.common import CATEGORIES
from app.keyboards.events import event_keyboard, private_event_keyboard
from app.utils.html import safe_html

logger = logging.getLogger(__name__)

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024
_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

ARCHIVED_TEXT = "🏁 Встреча завершена. История и оценки сохранены."
DELETED_TEXT = "🗑 Эта встреча отменена организатором."

_MISSING_MARKERS = (
    "message to edit not found",
    "message to delete not found",
    "message can't be edited",
    "message can't be deleted",
    "chat not found",
    "bot was kicked",
    "bot is not a member",
    "not enough rights",
    "message identifier is not specified",
)


# --------------------------------------------------------------------------- #
# Счётчики и выборки
# --------------------------------------------------------------------------- #
async def event_count(session: AsyncSession, event_id: int) -> int:
    """Число записанных участников."""
    stmt = select(func.count(Signup.id)).where(Signup.event_id == event_id)
    return int((await session.execute(stmt)).scalar() or 0)


def _to_dict(event: Event, booked: int) -> dict:
    """Плоский dict, совместимый со старым sqlite3.Row."""
    return {
        "id": event.id,
        "owner_id": event.owner_id,
        "owner_name": event.owner_name or "",
        "owner_username": event.owner_username or "",
        "title": event.title,
        "description": event.description or "",
        "category": event.category or "other",
        "starts_at": event.starts_at,
        "address": event.address,
        "conditions": event.conditions,
        "capacity": event.capacity,
        "source_chat_id": event.source_chat_id,
        "source_chat_title": event.source_chat_title or "",
        "visibility": event.visibility or "public",
        "photo_file_id": event.photo_file_id or "",
        "created_at": event.created_at,
        "booked": booked,
        "available": max(0, event.capacity - booked),
    }


async def event_with_count(session: AsyncSession, event_id: int) -> dict | None:
    """Одна встреча со счётчиками."""
    stmt = (
        select(Event, func.count(Signup.id))
        .outerjoin(Signup, Signup.event_id == Event.id)
        .where(Event.id == event_id)
        .group_by(Event.id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    event, booked = row
    return _to_dict(event, int(booked or 0))


# Совместимость с именем из шага 2
get_event_with_count = event_with_count


async def events_with_counts(
    session: AsyncSession,
    event_ids: Sequence[int],
) -> list[dict]:
    """Батч-выборка без N+1. Порядок — как в event_ids."""
    if not event_ids:
        return []
    stmt = (
        select(Event, func.count(Signup.id))
        .outerjoin(Signup, Signup.event_id == Event.id)
        .where(Event.id.in_(event_ids))
        .group_by(Event.id)
    )
    rows = (await session.execute(stmt)).all()
    mapping = {event.id: _to_dict(event, int(booked or 0)) for event, booked in rows}
    return [mapping[eid] for eid in event_ids if eid in mapping]


# --------------------------------------------------------------------------- #
# Текст карточки (HTML)
# --------------------------------------------------------------------------- #
def _organizer_line(event: dict) -> str:
    username = (event.get("owner_username") or "").strip().lstrip("@")
    if username:
        return f"👤 Организатор: @{safe_html(username)}"
    name = (event.get("owner_name") or "").strip()
    return f"👤 Организатор: {safe_html(name or 'не указан')}"


def _card_blocks(event: dict, private_details: bool) -> tuple[list[str], str, list[str]]:
    dt: datetime = event["starts_at"].astimezone(settings.tzinfo)
    head = [
        f"📌 <b>{safe_html(event['title'])}</b>",
        f"🏷 {CATEGORIES.get(event['category'], CATEGORIES.get('other', 'Другое'))}",
        f"🗓 {dt:%d.%m.%Y} ({_WEEKDAYS[dt.weekday()]}) в {dt:%H:%M} МСК",
        f"📍 {safe_html(event['address'])}",
    ]

    description = (event.get("description") or "").strip()

    tail = [f"⚙️ Условия: {safe_html(event['conditions'])}",
            f"👥 Записано: {event['booked']}/{event['capacity']} · свободно {event['available']}",
            _organizer_line(event)]

    if event.get("visibility") == "chat":
        source = (event.get("source_chat_title") or "").strip()
        tail.append(f"🔒 Только для чата{': ' + safe_html(source) if source else ''}")

    if private_details:
        tail.append(f"🆔 №{event['id']}")

    return head, description, tail


def _assemble(head: list[str], description: str, tail: list[str]) -> str:
    parts = list(head)
    if description:
        parts.append(f"📝 {safe_html(description)}")
    parts.extend(tail)
    return "\n".join(parts)


def event_card_text(
    event: dict,
    private_details: bool = False,
    *,
    max_len: int = TEXT_LIMIT,
) -> str:
    """HTML-текст карточки. Описание обрезается так, чтобы не порвать разметку."""
    head, description, tail = _card_blocks(event, private_details)

    text = _assemble(head, description, tail)
    if len(text) <= max_len:
        return text

    # Пробуем урезать описание, потом убрать совсем.
    overflow = len(text) - max_len
    keep = max(0, len(description) - overflow - 2)
    if keep >= 40:
        clipped = description[:keep].rstrip() + "…"
        text = _assemble(head, clipped, tail)
        if len(text) <= max_len:
            return text

    text = _assemble(head, "", tail)
    if len(text) <= max_len:
        return text + "\n📝 Описание сокращено"[: max(0, max_len - len(text))]

    # Крайний случай: очень длинные адрес/условия.
    return text[: max_len - 1] + "…"


# --------------------------------------------------------------------------- #
# Привязка сообщений
# --------------------------------------------------------------------------- #
async def remember_event_message(
    session: AsyncSession,
    event_id: int,
    chat_id: int,
    message_id: int,
) -> None:
    """INSERT … ON CONFLICT DO NOTHING (составной PK)."""
    stmt = (
        pg_insert(EventMessage)
        .values(event_id=event_id, chat_id=chat_id, message_id=message_id)
        .on_conflict_do_nothing(
            index_elements=["event_id", "chat_id", "message_id"]
        )
    )
    await session.execute(stmt)


async def forget_event_message(
    session: AsyncSession,
    event_id: int,
    chat_id: int,
    message_id: int,
) -> None:
    await session.execute(
        delete(EventMessage).where(
            EventMessage.event_id == event_id,
            EventMessage.chat_id == chat_id,
            EventMessage.message_id == message_id,
        )
    )


# --------------------------------------------------------------------------- #
# Низкоуровневые операции с сообщениями
# --------------------------------------------------------------------------- #
def _is_missing(exc: TelegramAPIError) -> bool:
    return any(marker in str(exc).lower() for marker in _MISSING_MARKERS)


async def _safe_call(coro_factory, *args, **kwargs):
    """Один повтор при flood-control, иначе — мягкое логирование."""
    for attempt in (1, 2):
        try:
            return await coro_factory(*args, **kwargs)
        except TelegramRetryAfter as exc:
            if attempt == 1:
                await asyncio.sleep(exc.retry_after + 1)
                continue
            logger.warning("Flood control: %s", exc)
            return None
        except (TelegramNotFound, TelegramForbiddenError) as exc:
            logger.info("Message unavailable: %s", exc)
            return None
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return None
            raise
        except TelegramAPIError as exc:
            logger.info("Telegram API error: %s", exc)
            return None
    return None


async def edit_card(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    has_photo: bool,
    reply_markup=None,
) -> bool:
    """Обновляет текст или caption. Возвращает False, если сообщение недоступно."""
    try:
        if has_photo:
            await _safe_call(
                bot.edit_message_caption,
                chat_id=chat_id,
                message_id=message_id,
                caption=text[:CAPTION_LIMIT],
                reply_markup=reply_markup,
            )
        else:
            await _safe_call(
                bot.edit_message_text,
                chat_id=chat_id,
                message_id=message_id,
                text=text[:TEXT_LIMIT],
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        return True
    except TelegramBadRequest as exc:
        # Тип карточки мог измениться (фото ↔ текст) — пробуем второй способ.
        try:
            if has_photo:
                await _safe_call(
                    bot.edit_message_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text[:TEXT_LIMIT],
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
            else:
                await _safe_call(
                    bot.edit_message_caption,
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text[:CAPTION_LIMIT],
                    reply_markup=reply_markup,
                )
            return True
        except TelegramAPIError as inner:
            logger.info("Could not edit card %s/%s: %s", chat_id, message_id, inner)
            return not _is_missing(inner)
    except TelegramAPIError as exc:
        logger.info("Could not edit card %s/%s: %s", chat_id, message_id, exc)
        return not _is_missing(exc)


async def archive_card(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    has_photo: bool,
    unpin: bool = True,
    delete_first: bool = True,
) -> None:
    """Снимает интерактив с карточки: удаляет, иначе редактирует."""
    if unpin:
        await _safe_call(bot.unpin_chat_message, chat_id=chat_id, message_id=message_id)

    if delete_first:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            return
        except TelegramAPIError:
            pass  # старше 48 ч / нет прав — редактируем

    await edit_card(
        bot,
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        has_photo=has_photo,
        reply_markup=None,
    )


# --------------------------------------------------------------------------- #
# Обновление карточек
# --------------------------------------------------------------------------- #
async def refresh_event_messages(
    bot: Bot,
    event_id: int,
    *,
    session: AsyncSession | None = None,
) -> int:
    """Перерисовывает все карточки встречи.

    ВАЖНО: вызывать ПОСЛЕ commit(), иначе отдельная сессия не увидит изменения.
    Если передан session — используется она (вызывающий сам управляет транзакцией).
    """
    if session is not None:
        return await _refresh_in_session(bot, event_id, session)

    from app.db.engine import session_scope

    async with session_scope() as own_session:
        return await _refresh_in_session(bot, event_id, own_session)


async def _refresh_in_session(bot: Bot, event_id: int, session: AsyncSession) -> int:
    event = await event_with_count(session, event_id)
    if event is None:
        return 0

    rows = (
        await session.execute(
            select(EventMessage).where(EventMessage.event_id == event_id)
        )
    ).scalars().all()

    if not rows:
        return 0

    me = await bot.me()
    bot_username = me.username
    has_photo = bool(event["photo_file_id"])
    limit = CAPTION_LIMIT if has_photo else TEXT_LIMIT

    group_text = event_card_text(event, private_details=False, max_len=limit)
    private_text = event_card_text(event, private_details=True, max_len=limit)
    group_kb = event_keyboard(event, None, bot_username=bot_username)

    updated = 0
    stale: list[EventMessage] = []

    for msg in rows:
        is_private = msg.chat_id > 0
        text = private_text if is_private else group_text
        kb = (
            private_event_keyboard(event, msg.chat_id, bot_username=bot_username)
            if is_private
            else group_kb
        )

        ok = await edit_card(
            bot,
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            text=text,
            has_photo=has_photo,
            reply_markup=kb,
        )
        if ok:
            updated += 1
        else:
            stale.append(msg)

    for msg in stale:
        await forget_event_message(session, msg.event_id, msg.chat_id, msg.message_id)

    return updated


async def archive_event_messages(bot: Bot, targets: Iterable[tuple[int, int]], text: str) -> None:
    """Архивирует переданный список (chat_id, message_id) без обращения к БД."""
    for chat_id, message_id in targets:
        await archive_card(
            bot,
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            has_photo=False,
            delete_first=False,
        )


# --------------------------------------------------------------------------- #
# Фоновая очистка завершившихся встреч
# --------------------------------------------------------------------------- #
async def cleanup_finished_event_cards(bot: Bot, *, limit: int = 150) -> int:
    """Убирает карточки завершившихся встреч. Сами встречи и статистика целы."""
    from app.db.engine import session_scope

    now = utcnow()
    processed = 0

    async with session_scope() as session:
        stmt = (
            select(
                EventMessage.event_id,
                EventMessage.chat_id,
                EventMessage.message_id,
                Event.photo_file_id,
            )
            .join(Event, Event.id == EventMessage.event_id)
            .where(Event.starts_at <= now)
            .order_by(Event.starts_at)
            .limit(limit)
        )
        targets = (await session.execute(stmt)).all()

        for event_id, chat_id, message_id, photo_file_id in targets:
            await archive_card(
                bot,
                chat_id=chat_id,
                message_id=message_id,
                text=ARCHIVED_TEXT,
                has_photo=bool(photo_file_id),
            )
            await forget_event_message(session, event_id, chat_id, message_id)
            processed += 1

        # Забываем Telegram file_id после начала встречи — история остаётся.
        await session.execute(
            update(Event)
            .where(Event.starts_at <= now, Event.photo_file_id != "")
            .values(photo_file_id="")
        )
        # commit выполнит session_scope

    if processed:
        logger.info("Finished-event cleanup: processed %d cards", processed)
    return processed