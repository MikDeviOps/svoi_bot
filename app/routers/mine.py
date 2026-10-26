"""/mine + редактирование + управление участниками + удаление.

UX:
- Всё, что «не на своё» (edit, delete, manage, kick) → alert
  «Это не ваша встреча».
- edit_text вместо answer (без спама).
"""

from __future__ import annotations

from datetime import datetime

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot_states import EditEvent
from app.db import Event
from app.errors import DomainError
from app.keyboards import confirm_delete_kb, edit_menu_kb, mine_kb, participants_kb
from app.services.events import EventService
from app.services.notifications import enqueue_refresh
from app.services.signups import SignupService

logger = structlog.get_logger(__name__)
router = Router(name="mine")


# ---------------------------------------------------------------------------
# /mine
# ---------------------------------------------------------------------------


@router.message(Command("mine"))
async def mine(message: Message, session: AsyncSession) -> None:
    if message.chat.type != "private":
        await message.answer("Команда /mine доступна в личном чате с ботом.")
        return

    service = EventService(session)
    events = await service.list_by_owner(message.from_user.id)
    if not events:
        await message.answer("У вас пока нет предстоящих встреч. /create")
        return

    await message.answer("Ваши встречи:")
    for e in events:
        await message.answer(
            f"№{e.id} · {e.title} · {e.starts_at.strftime('%d.%m.%Y %H:%M')} · "
            f"{e.booked}/{e.capacity}",
            reply_markup=mine_kb(e.id),
        )


@router.message(F.text.in_({"📋 Мои встречи"}))
async def text_mine(message: Message, session: AsyncSession) -> None:
    await mine(message, session=session)


# ---------------------------------------------------------------------------
# Удаление
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("deleteask:"))
async def cb_delete_ask(query: CallbackQuery, session: AsyncSession) -> None:
    event_id = int(query.data.split(":", 1)[1])
    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        await query.answer("Встреча не найдена.", show_alert=True)
        return
    if event.owner_id != query.from_user.id:
        await query.answer("Это не ваша встреча.", show_alert=True)
        return
    await query.answer()
    await query.message.edit_text(
        f"Удалить встречу «{event.title}»? Записи участников тоже будут удалены.",
        reply_markup=confirm_delete_kb(event_id),
    )


@router.callback_query(F.data.startswith("deleteconfirm:"))
async def cb_delete_confirm(query: CallbackQuery, session: AsyncSession) -> None:
    event_id = int(query.data.split(":", 1)[1])
    service = EventService(session)
    try:
        await service.soft_delete(event_id, query.from_user.id)
    except DomainError as exc:
        await query.answer(exc.user_message, show_alert=True)
        return
    await query.answer()
    await query.message.edit_text("🗑 Встреча удалена.")


@router.callback_query(F.data.startswith("deletecancel:"))
async def cb_delete_cancel(query: CallbackQuery) -> None:
    await query.answer("Удаление отменено.")
    await query.message.edit_text("Удаление отменено.")


# ---------------------------------------------------------------------------
# Управление участниками
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("managepeople:"))
async def cb_manage_people(query: CallbackQuery, session: AsyncSession) -> None:
    event_id = int(query.data.split(":", 1)[1])
    event = await session.get(Event, event_id)
    if event is None or event.owner_id != query.from_user.id:
        await query.answer("Это не ваша встреча.", show_alert=True)
        return

    service = SignupService(session)
    people = await service.list_participants(event_id)
    if not people:
        await query.answer("Пока никто не записался.", show_alert=True)
        return

    rows = [(p.user_id, p.telegram_name or str(p.user_id)) for p in people]
    await query.answer()
    await query.message.edit_text(
        "Кого удалить?", reply_markup=participants_kb(event_id, rows)
    )


@router.callback_query(F.data.startswith("kickask:"))
async def cb_kick_ask(query: CallbackQuery, session: AsyncSession) -> None:
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer("Неверный запрос.", show_alert=True)
        return
    event_id, user_id = int(parts[1]), int(parts[2])
    event = await session.get(Event, event_id)
    if event is None or event.owner_id != query.from_user.id:
        await query.answer("Это не ваша встреча.", show_alert=True)
        return
    await query.answer()
    await query.message.edit_text(
        f"Удалить участника {user_id}?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Да, удалить",
                callback_data=f"kickconfirm:{event_id}:{user_id}",
            ),
            InlineKeyboardButton(
                text="Нет",
                callback_data=f"kickcancel:{event_id}:{user_id}",
            ),
        ]]),
    )


@router.callback_query(F.data.startswith("kickconfirm:"))
async def cb_kick_confirm(query: CallbackQuery, session: AsyncSession) -> None:
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer("Неверный запрос.", show_alert=True)
        return
    event_id, user_id = int(parts[1]), int(parts[2])
    service = SignupService(session)
    try:
        await service.kick(event_id, query.from_user.id, user_id)
    except DomainError as exc:
        await query.answer(exc.user_message, show_alert=True)
        return
    await enqueue_refresh(event_id, session, query.bot)
    await query.answer()
    await query.message.edit_text("✅ Участник удалён. Место освобождено.")


@router.callback_query(F.data.startswith("kickcancel:"))
async def cb_kick_cancel(query: CallbackQuery) -> None:
    await query.answer("Удаление отменено.")
    await query.message.edit_text("Удаление отменено.")


# ---------------------------------------------------------------------------
# Редактирование
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("editmenu:"))
async def cb_edit_menu(query: CallbackQuery, session: AsyncSession) -> None:
    event_id = int(query.data.split(":", 1)[1])
    event = await session.get(Event, event_id)
    if event is None or event.owner_id != query.from_user.id:
        await query.answer("Это не ваша встреча.", show_alert=True)
        return
    await query.answer()
    await query.message.edit_text(
        "Что изменить?", reply_markup=edit_menu_kb(event_id)
    )


@router.callback_query(F.data.startswith("editfield:"))
async def cb_edit_field(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer("Неверный запрос.", show_alert=True)
        return
    event_id, field = int(parts[1]), parts[2]
    # Проверка «не на своё»
    event = await session.get(Event, event_id)
    if event is None or event.owner_id != query.from_user.id:
        await query.answer("Это не ваша встреча.", show_alert=True)
        return

    await state.update_data(edit_event_id=event_id, edit_field=field)
    await state.set_state(EditEvent.field_value)
    await query.answer()
    hints = {"date": "ДД.ММ.ГГГГ", "time": "ЧЧ:ММ", "capacity": "1–1000"}
    await query.message.answer(
        f"Введите новое значение ({hints.get(field, 'текст')}):\n/cancel — отмена"
    )


@router.message(EditEvent.field_value)
async def step_edit_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    event_id = data["edit_event_id"]
    field = data["edit_field"]
    raw = message.text.strip()

    service = EventService(session)

    try:
        if field == "date":
            d = datetime.strptime(raw, "%d.%m.%Y").date()
            event = await session.get(Event, event_id)
            starts_at = datetime.combine(d, event.starts_at.time()).replace(
                tzinfo=event.starts_at.tzinfo
            )
            await service.update(event_id, message.from_user.id, "starts_at", starts_at)
        elif field == "time":
            t = datetime.strptime(raw, "%H:%M").time()
            event = await session.get(Event, event_id)
            starts_at = datetime.combine(event.starts_at.date(), t).replace(
                tzinfo=event.starts_at.tzinfo
            )
            await service.update(event_id, message.from_user.id, "starts_at", starts_at)
        elif field == "capacity":
            await service.update(event_id, message.from_user.id, "capacity", int(raw))
        else:
            await service.update(event_id, message.from_user.id, field, raw)
    except (ValueError, DomainError) as exc:
        msg = exc.user_message if isinstance(exc, DomainError) else "Неверный формат."
        await message.answer(f"❗ {msg} Попробуйте ещё раз или /cancel.")
        return

    await state.clear()
    await enqueue_refresh(event_id, session, message.bot)
    await message.answer("✅ Встреча обновлена.")


@router.message(Command("cancel"), EditEvent.field_value)
async def cancel_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Редактирование отменено.")