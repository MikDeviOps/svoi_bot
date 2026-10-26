"""Карточки событий и действия. UX: edit_text вместо answer, alerts."""

from __future__ import annotations

from html import escape

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Event, EventMessage, User
from app.errors import CapacityFull, Conflict, DomainError, PastEvent
from app.keyboards import event_kb
from app.services.events import _count_booked
from app.services.notifications import enqueue_refresh, render_card
from app.services.permissions import can_access_event
from app.services.signups import SignupService

logger = structlog.get_logger(__name__)
router = Router(name="events")


async def _save_event_message(
    session: AsyncSession, sent_message: Message, event_id: int
) -> None:
    session.add(EventMessage(
        event_id=event_id,
        chat_id=sent_message.chat.id,
        message_id=sent_message.message_id,
    ))
    await session.flush()


async def send_event_card(
    message: Message,
    session: AsyncSession,
    event: Event,
    *,
    private_details: bool = True,
    viewer_id: int | None = None,
) -> Message:
    booked = await _count_booked(session, event.id)
    owner = await session.get(User, event.owner_id)
    text = render_card(
        event, booked,
        owner_name=owner.full_name if owner else "",
        owner_username=owner.username if owner else "",
        private_details=private_details,
    )
    kb = event_kb(event, booked, viewer_id=viewer_id)
    sent = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await _save_event_message(session, sent, event.id)
    return sent


# ---------------------------------------------------------------------------
# detail — edit_text (та же карточка → подробнее)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("detail:"))
async def cb_detail(query: CallbackQuery, session: AsyncSession) -> None:
    try:
        event_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверный номер.", show_alert=True)
        return

    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        await query.answer("Встреча не найдена.", show_alert=True)
        return

    if not await can_access_event(
        event,
        chat_id=query.message.chat.id,
        chat_type=query.message.chat.type,
        user_id=query.from_user.id,
        bot=query.bot,
    ):
        await query.answer(
            "Встреча доступна только участникам чата-организатора.",
            show_alert=True,
        )
        return

    booked = await _count_booked(session, event_id)
    owner = await session.get(User, event.owner_id)
    text = render_card(
        event, booked,
        owner_name=owner.full_name if owner else "",
        owner_username=owner.username if owner else "",
        private_details=True,
    )
    kb = event_kb(event, booked, viewer_id=query.from_user.id)

    await query.answer()
    # edit_text — НЕ новое сообщение
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ---------------------------------------------------------------------------
# join / cancel / full — alert, без сообщений
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("join:"))
async def cb_join(query: CallbackQuery, session: AsyncSession, user) -> None:
    try:
        event_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверный номер.", show_alert=True)
        return

    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        await query.answer("Встреча не найдена.", show_alert=True)
        return

    if not await can_access_event(
        event,
        chat_id=query.message.chat.id,
        chat_type=query.message.chat.type,
        user_id=query.from_user.id,
        bot=query.bot,
    ):
        await query.answer(
            "Записаться можно только участникам чата-организатора.",
            show_alert=True,
        )
        return

    if user is None or not hasattr(user, "tg_id"):
        user = await session.get(User, query.from_user.id)
    if user is None:
        await query.answer("Не удалось определить пользователя.", show_alert=True)
        return

    service = SignupService(session)
    try:
        result = await service.join(event_id, user)
    except (PastEvent, CapacityFull, DomainError) as exc:
        await query.answer(exc.user_message, show_alert=True)
        return

    if not result.joined:
        await query.answer(result.reason, show_alert=True)
        return

    await enqueue_refresh(event_id, session, query.bot)
    # Обновляем карточку через edit_text
    try:
        booked = await _count_booked(session, event_id)
        owner = await session.get(User, event.owner_id)
        text = render_card(
            event, booked,
            owner_name=owner.full_name if owner else "",
            owner_username=owner.username if owner else "",
            private_details=True,
        )
        kb = event_kb(event, booked, viewer_id=query.from_user.id)
        await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass   # не падаем, если карточка уже не та

    await query.answer(
        f"✅ Вы записаны. Свободно мест: {result.available}.",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("full:"))
async def cb_full(query: CallbackQuery) -> None:
    await query.answer("На эту встречу уже нет свободных мест.", show_alert=True)


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(query: CallbackQuery, session: AsyncSession) -> None:
    try:
        event_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверный номер.", show_alert=True)
        return

    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        await query.answer("Встреча не найдена.", show_alert=True)
        return

    service = SignupService(session)
    try:
        result = await service.cancel(event_id, query.from_user.id)
    except (Conflict, DomainError) as exc:
        await query.answer(exc.user_message, show_alert=True)
        return

    await enqueue_refresh(event_id, session, query.bot)
    try:
        booked = await _count_booked(session, event_id)
        owner = await session.get(User, event.owner_id)
        text = render_card(
            event, booked,
            owner_name=owner.full_name if owner else "",
            owner_username=owner.username if owner else "",
            private_details=True,
        )
        kb = event_kb(event, booked, viewer_id=query.from_user.id)
        await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass

    await query.answer(
        f"❌ Запись отменена. Свободно мест: {result.available}.",
        show_alert=True,
    )


# ---------------------------------------------------------------------------
# participants — edit_text (карточка → участники)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("participants:"))
async def cb_participants(query: CallbackQuery, session: AsyncSession) -> None:
    try:
        event_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверный номер.", show_alert=True)
        return

    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        await query.answer("Встреча не найдена.", show_alert=True)
        return

    if not await can_access_event(
        event,
        chat_id=query.message.chat.id,
        chat_type=query.message.chat.type,
        user_id=query.from_user.id,
        bot=query.bot,
    ):
        await query.answer(
            "Список участников доступен только участникам чата-организатора.",
            show_alert=True,
        )
        return

    service = SignupService(session)
    participants = await service.list_participants(event_id)
    heading = (
        f"👥 Участники встречи «{escape(event.title)}»\n"
        f"Записано: {len(participants)}/{event.capacity}"
    )

    if not participants:
        await query.answer()
        await query.message.edit_text(f"{heading}\nПока никто не записался.")
        return

    names = [
        (p.telegram_name or "Имя не указано").replace("\r", " ").replace("\n", " ")
        for p in participants
    ]

    chunks = []
    current = heading
    for name in names:
        line = f"\n• {escape(name)}"
        if len(current) + len(line) > 3800:
            chunks.append(current)
            current = "👥 Участники (продолжение)"
        current += line
    chunks.append(current)

    await query.answer()
    # edit_text — заменяет карточку на список участников (1 сообщение)
    await query.message.edit_text(chunks[0], parse_mode="HTML")
    # Остальные chunk — если больше 3800 символов, они редки
    for chunk in chunks[1:]:
        await query.message.answer(chunk, parse_mode="HTML")