"""join / cancel / participants / detail + send_event_card + notify_source_group."""

from __future__ import annotations

from datetime import datetime

import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramError
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import Event, EventMessage, Signup, User
from app.errors import DomainError
from app.keyboards import event_kb, group_event_url_kb, participants_kb
from app.services.notifications import render_card
from app.services.signups import SignupService

logger = structlog.get_logger(__name__)
router = Router(name="events")


# ---------------------------------------------------------------------------
# Вспомогательные
# ---------------------------------------------------------------------------


async def _count_booked(session: AsyncSession, event_id: int) -> int:
    result = await session.scalar(
        select(func.count()).select_from(Signup).where(Signup.event_id == event_id)
    )
    return int(result or 0)


def _actions_available(event: Event) -> bool:
    """True, пока встреча не началась — кнопки join/cancel активны."""
    return event.starts_at > datetime.now(get_settings().timezone)


async def _save_event_message(
    session: AsyncSession, sent: Message, event_id: int
) -> None:
    """Запомнить карточку в event_messages для refresh счётчика мест.

    Не коммитит — коммит на уровне роутера.
    """
    session.add(EventMessage(
        event_id=event_id,
        chat_id=sent.chat.id,
        message_id=sent.message_id,
    ))
    await session.flush()


async def _notify_source_group(
    bot: Bot,
    event: Event,
    user,
    available: int,
    *,
    joined: bool,
) -> None:
    """Уведомить исходную группу о join/cancel. Ошибки не роняют хендлер."""
    if event.source_chat_id is None:
        return
    from html import escape

    action = "записался(ась)" if joined else "отменил(а) запись"
    icon = "✅" if joined else "❌"
    full_name = getattr(user, "full_name", None) or str(getattr(user, "id", "?"))
    user_id = getattr(user, "id", None)
    if user_id is not None:
        mention = f'<a href="tg://user?id={user_id}">{escape(full_name)}</a>'
    else:
        mention = escape(full_name)
    text = (
        f"{icon} {mention} {action} на встречу «{escape(event.title)}».\n"
        f"👥 Свободно мест: {available}."
    )
    try:
        await bot.send_message(
            chat_id=event.source_chat_id, text=text, parse_mode="HTML"
        )
    except TelegramError as exc:
        logger.warning(
            "notify_source_group_failed", event_id=event.id, error=str(exc)
        )


# ---------------------------------------------------------------------------
# Универсальная отправка карточки
# ---------------------------------------------------------------------------


async def send_event_card(
    message: Message,
    session: AsyncSession,
    event: Event,
    *,
    private_details: bool = True,
    viewer_id: int | None = None,
    chat_id: int | None = None,
) -> Message:
    """Отправить карточку встречи.

    - ``chat_id is None``  → в текущий чат (``message.answer``), для лички/афиши.
    - ``chat_id < 0``      → в группу через ``bot.send_message``/``send_photo``
                              с URL-кнопкой «Открыть в боте» (``group_event_url_kb``).
    - ``chat_id > 0``      → в личку по явному id.
    """
    booked = await _count_booked(session, event.id)
    owner = await session.get(User, event.owner_id)
    text = render_card(
        event, booked,
        owner_name=owner.full_name if owner else "",
        owner_username=owner.username if owner else "",
        private_details=private_details,
    )

    target = chat_id if chat_id is not None else message.chat.id

    if int(target) < 0:
        # Группа: только URL-кнопка «Открыть в боте», callback'и не ставим.
        me = await message.bot.get_me()
        kb = group_event_url_kb(me.username, event.id)
    else:
        # Личка: обычный event_kb с join/cancel/detail.
        kb = event_kb(
            event, booked,
            viewer_id=viewer_id,
            show_detail=True,
            show_actions=_actions_available(event),
        )

    if chat_id is not None:
        # Явный chat_id — отправляем через bot, не через message.answer.
        if event.photo_file_id:
            sent = await message.bot.send_photo(
                chat_id=chat_id,
                photo=event.photo_file_id,
                caption=text[:1024],
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            sent = await message.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
    else:
        # Текущий чат — message.answer / answer_photo.
        if event.photo_file_id:
            sent = await message.answer_photo(
                photo=event.photo_file_id,
                caption=text[:1024],
                reply_markup=kb,
                parse_mode="HTML",
            )
        else:
            sent = await message.answer(
                text, reply_markup=kb, parse_mode="HTML",
            )

    await _save_event_message(session, sent, event.id)
    return sent


# ---------------------------------------------------------------------------
# Бизнес-обработчики (для deep-link и callback)
# ---------------------------------------------------------------------------


async def handle_join(message: Message, event_id: int, session: AsyncSession) -> None:
    service = SignupService(session)
    try:
        result = await service.join(event_id, message.from_user)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await session.commit()

    event = await session.get(Event, event_id)
    if event is None:
        return
    available = max(0, event.capacity - result.booked)
    await _notify_source_group(
        message.bot, event, message.from_user, available, joined=True
    )
    await message.answer(result.user_message)


async def handle_cancel(message: Message, event_id: int, session: AsyncSession) -> None:
    service = SignupService(session)
    try:
        result = await service.cancel(event_id, message.from_user.id)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await session.commit()

    event = await session.get(Event, event_id)
    if event is None:
        return
    available = max(0, event.capacity - result.booked)
    await _notify_source_group(
        message.bot, event, message.from_user, available, joined=False
    )
    await message.answer(result.user_message)


async def handle_participants(
    message: Message, event_id: int, session: AsyncSession
) -> None:
    event = await session.get(Event, event_id)
    if event is None:
        await message.answer("Встреча не найдена.")
        return

    # Для visibility=chat — только участникам чата-организатора.
    if event.visibility == "chat" and event.source_chat_id is not None:
        if message.chat.type == "private":
            try:
                member = await message.bot.get_chat_member(
                    chat_id=event.source_chat_id,
                    user_id=message.from_user.id,
                )
                status = getattr(member.status, "value", member.status)
                if status not in {"creator", "administrator", "member"}:
                    raise ValueError
            except (TelegramError, ValueError):
                await message.answer(
                    "Список доступен только участникам чата-организатора."
                )
                return
        elif message.chat.id != event.source_chat_id:
            await message.answer(
                "Список доступен только участникам чата-организатора."
            )
            return

    service = SignupService(session)
    people = await service.list_participants(event_id)
    lines = [
        f"👥 Участники встречи «{event.title}»",
        f"Записано: {len(people)}/{event.capacity}",
        "",
    ]
    if not people:
        lines.append("Пока никто не записался.")
    else:
        lines += [f"• {p.telegram_name}" for p in people]
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------------------
# Callback-хендлеры
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("join:"))
async def cb_join(query: CallbackQuery, session: AsyncSession) -> None:
    try:
        event_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверная встреча.", show_alert=True)
        return
    await query.answer()
    await handle_join(query.message, event_id, session)


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(query: CallbackQuery, session: AsyncSession) -> None:
    try:
        event_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверная встреча.", show_alert=True)
        return
    await query.answer()
    await handle_cancel(query.message, event_id, session)


@router.callback_query(F.data.startswith("participants:"))
async def cb_participants(query: CallbackQuery, session: AsyncSession) -> None:
    try:
        event_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверная встреча.", show_alert=True)
        return
    await query.answer()
    await handle_participants(query.message, event_id, session)


@router.callback_query(F.data.startswith("detail:"))
async def cb_detail(query: CallbackQuery, session: AsyncSession) -> None:
    try:
        event_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверная встреча.", show_alert=True)
        return
    await query.answer()

    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        await query.message.answer("Встреча не найдена.")
        return

    booked = await _count_booked(session, event_id)
    owner = await session.get(User, event.owner_id)
    text = render_card(
        event, booked,
        owner_name=owner.full_name if owner else "",
        owner_username=owner.username if owner else "",
        private_details=True,
    )
    kb = event_kb(
        event, booked,
        viewer_id=query.from_user.id,
        show_detail=False,
        show_actions=_actions_available(event),
    )
    if event.photo_file_id:
        await query.message.answer_photo(
            photo=event.photo_file_id,
            caption=text[:1024],
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await query.message.answer(
            text, reply_markup=kb, parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("full:"))
async def cb_full(query: CallbackQuery) -> None:
    await query.answer("На эту встречу уже нет свободных мест.", show_alert=True)