"""FSM создания встречи: title → description → category → date → time →
address → conditions → capacity → visibility → group.

Групповой ``/create`` → регистрация ``known_groups`` + ссылка в личку
→ deep-link ``create_<chat_id>`` → этот FSM.

Текстовый триггер ``➕ Создать встречу`` (ReplyKeyboard) = ``/create``.
"""

from __future__ import annotations

from datetime import date, datetime, time

import structlog
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot_states import CreateEvent
from app.config import get_settings
from app.db import KnownGroup, User
from app.errors import DomainError, Forbidden, ValidationError
from app.keyboards import (
    create_category_kb,
    create_visibility_kb,
    group_picker_kb,
    main_menu,
    private_link_kb,
)
from app.schemas import EventDraft
from app.services.events import EventService
from app.services.permissions import is_group_admin

logger = structlog.get_logger(__name__)
router = Router(name="create")


# ---------------------------------------------------------------------------
# Entry: /create в личке → выбрать группу; /create в группе → ссылка в личку
# ---------------------------------------------------------------------------


@router.message(Command("create"), StateFilter(None))
async def create_command(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.chat.type == "private":
        result = await session.execute(select(KnownGroup).order_by(KnownGroup.title))
        groups = list(result.scalars().all())

        accessible = []
        for g in groups:
            if await is_group_admin(message.bot, g.chat_id, message.from_user.id):
                accessible.append((g.chat_id, g.title))

        if not accessible:
            await message.answer(
                "Пока нет доступных групп. Добавьте бота в свою группу, "
                "отправьте там /create один раз, затем вернитесь в личку."
            )
            return

        await state.set_state(CreateEvent.group)
        await message.answer(
            "Выберите группу, от имени которой создаёте встречу:",
            reply_markup=group_picker_kb(accessible),
        )
        return

    if not await is_group_admin(message.bot, message.chat.id, message.from_user.id):
        await message.answer("Создавать встречи от группы могут только её администраторы.")
        return

    session.add(KnownGroup(chat_id=message.chat.id, title=message.chat.title or "Группа"))
    await session.flush()

    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start=create_{message.chat.id}"
    await message.answer(
        "Группа зарегистрирована. Продолжите создание встречи в личке с ботом:",
        reply_markup=private_link_kb(link),
    )


@router.message(F.text.in_({"➕ Создать встречу", "создать встречу"}), StateFilter(None))
async def text_create(message: Message, session: AsyncSession, state: FSMContext) -> None:
    """Текстовый триггер ReplyKeyboard ``➕ Создать встречу`` = /create."""
    await create_command(message, session=session, state=state)


async def start_create_from_group(
    message: Message,
    chat_id: int,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Точка входа из deep-link ``create_<chat_id>`` (уже в личке)."""
    await state.update_data(source_chat_id=chat_id)
    await state.set_state(CreateEvent.title)
    await message.answer("Название встречи? (от 3 до 100 символов, например: Посиделки в кафе)")


# ---------------------------------------------------------------------------
# FSM: шаги
# ---------------------------------------------------------------------------


@router.callback_query(CreateEvent.group, F.data.startswith("newgroup:"))
async def step_group(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    try:
        chat_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("Неверная группа.")
        return

    known = await session.get(KnownGroup, chat_id)
    if known is None:
        await query.answer("Группа не найдена. Начните заново: /create")
        await state.clear()
        return

    await state.update_data(source_chat_id=chat_id, source_chat_title=known.title)
    await state.set_state(CreateEvent.title)
    await query.answer()
    await query.message.edit_text("Название встречи? (от 3 до 100 символов)")


@router.message(CreateEvent.title)
async def step_title(message: Message, state: FSMContext) -> None:
    try:
        draft = EventDraft(title=message.text)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await state.update_data(title=draft.title)
    await state.set_state(CreateEvent.description)
    await message.answer("Описание (до 1000 символов) или '-' без описания:")


@router.message(CreateEvent.description)
async def step_description(message: Message, state: FSMContext) -> None:
    value = "" if message.text.strip() == "-" else message.text
    try:
        draft = EventDraft(description=value)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await state.update_data(description=draft.description)
    await state.set_state(CreateEvent.category)
    await message.answer("Категория:", reply_markup=create_category_kb())


@router.callback_query(CreateEvent.category, F.data.startswith("newcat:"))
async def step_category(query: CallbackQuery, state: FSMContext) -> None:
    slug = query.data.split(":", 1)[1]
    try:
        draft = EventDraft(category=slug)
    except DomainError as exc:
        await query.answer(exc.user_message, show_alert=True)
        return
    await state.update_data(category=draft.category)
    await state.set_state(CreateEvent.date)
    await query.answer()
    await query.message.edit_text("Дата в формате ДД.ММ.ГГГГ (например, 26.10.2026):")


@router.message(CreateEvent.date)
async def step_date(message: Message, state: FSMContext) -> None:
    try:
        d = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("Формат: ДД.ММ.ГГГГ. Попробуйте ещё раз.")
        return
    try:
        draft = EventDraft(event_date=d)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await state.update_data(event_date=draft.event_date)
    await state.set_state(CreateEvent.time)
    await message.answer("Время по Москве, ЧЧ:ММ (например, 19:00):")


@router.message(CreateEvent.time)
async def step_time(message: Message, state: FSMContext) -> None:
    try:
        t = datetime.strptime(message.text.strip(), "%H:%M").time()
    except ValueError:
        await message.answer("Формат: ЧЧ:ММ. Попробуйте ещё раз.")
        return
    data = await state.get_data()
    try:
        draft = EventDraft(event_date=data["event_date"], event_time=t)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await state.update_data(event_time=t)
    await state.set_state(CreateEvent.address)
    await message.answer("Адрес (метро, улица, дом):")


@router.message(CreateEvent.address)
async def step_address(message: Message, state: FSMContext) -> None:
    try:
        draft = EventDraft(address=message.text)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await state.update_data(address=draft.address)
    await state.set_state(CreateEvent.conditions)
    await message.answer("Условия (например: депозит 500 ₽ организатору):")


@router.message(CreateEvent.conditions)
async def step_conditions(message: Message, state: FSMContext) -> None:
    try:
        draft = EventDraft(conditions=message.text)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await state.update_data(conditions=draft.conditions)
    await state.set_state(CreateEvent.capacity)
    await message.answer("Максимум участников (от 1 до 1000):")


@router.message(CreateEvent.capacity)
async def step_capacity(message: Message, state: FSMContext) -> None:
    try:
        value = int(message.text.strip())
        draft = EventDraft(capacity=value)
    except (ValueError, DomainError) as exc:
        msg = exc.user_message if isinstance(exc, DomainError) else "Введите число от 1 до 1000."
        await message.answer(msg)
        return
    await state.update_data(capacity=draft.capacity)
    await state.set_state(CreateEvent.visibility)
    data = await state.get_data()
    has_group = data.get("source_chat_id") is not None
    await message.answer("Кому видна встреча?", reply_markup=create_visibility_kb(has_group))


@router.callback_query(CreateEvent.visibility, F.data.startswith("newvisibility:"))
async def step_visibility(
    query: CallbackQuery, state: FSMContext, session: AsyncSession, user
) -> None:
    visibility = query.data.split(":", 1)[1]
    if visibility not in {"public", "chat"}:
        await query.answer("Неверная видимость.")
        return

    data = await state.get_data()
    try:
        draft = EventDraft(
            title=data["title"],
            description=data.get("description", ""),
            category=data["category"],
            event_date=data["event_date"],
            event_time=data["event_time"],
            address=data["address"],
            conditions=data["conditions"],
            capacity=data["capacity"],
            visibility=visibility,
            source_chat_id=data.get("source_chat_id"),
            source_chat_title=data.get("source_chat_title", ""),
        )
    except DomainError as exc:
        await query.answer(exc.user_message, show_alert=True)
        await state.clear()
        return

    service = EventService(session)
    try:
        event_view = await service.create(draft, owner_id=query.from_user.id)
    except DomainError as exc:
        await query.answer(exc.user_message, show_alert=True)
        await state.clear()
        return

    await state.clear()
    await query.answer()
    await query.message.edit_text(
        f"✅ Встреча №{event_view.id} создана.\n"
        f"/vstrechi — открыть афишу."
    )


# ---------------------------------------------------------------------------
# /cancel
# ---------------------------------------------------------------------------


@router.message(Command("cancel"), StateFilter("*"))
async def cancel_create(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание отменено.")