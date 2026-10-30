"""FSM создания: group → title → description → category → date → time →
address → conditions → capacity → visibility → photo → save."""

from __future__ import annotations

from datetime import datetime

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot_states import CreateEvent
from app.db import Event, KnownGroup
from app.errors import DomainError
from app.keyboards import (
    create_category_kb,
    create_visibility_kb,
    group_picker_kb,
    private_link_kb,
)
from app.schemas import EventDraft
from app.services.events import EventService
from app.services.locations import normalize_moscow_address
from app.services.permissions import is_group_admin

logger = structlog.get_logger(__name__)
router = Router(name="create")


# ---------------------------------------------------------------------------
# Выход из FSM по «чужим» командам/кнопкам
# ---------------------------------------------------------------------------

_COMMANDS = {"/start", "/vstrechi", "/today", "/create", "/mine", "/help", "/cancel"}
_BUTTONS = {"📅 Афиша встреч", "📋 Мои встречи", "❓ Помощь", "➕ Создать встречу"}


def _is_exit_intent(text: str | None) -> bool:
    if not text:
        return False
    t = text.strip()
    return t in _COMMANDS or t in _BUTTONS or (t.startswith("/") and t.split()[0] in _COMMANDS)


async def _handle_exit_intent(message: Message, state: FSMContext) -> bool:
    if not _is_exit_intent(message.text):
        return False
    await state.clear()
    await message.answer("Создание отменено. Используйте /create.")
    return True


@router.message(Command("cancel"), StateFilter("*"))
async def cancel_create(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Создание отменено.")


# ---------------------------------------------------------------------------
# Вход в FSM: /create, кнопка, deep-link create_<chat_id>
# ---------------------------------------------------------------------------


@router.message(Command("create"), StateFilter(None))
async def create_command(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if message.chat.type == "private":
        result = await session.execute(select(KnownGroup).order_by(KnownGroup.title))
        accessible: list[tuple[int, str]] = []
        for g in list(result.scalars().all()):
            if await is_group_admin(message.bot, g.chat_id, message.from_user.id):
                accessible.append((g.chat_id, g.title))
        if not accessible:
            await message.answer(
                "Пока нет доступных групп. Добавьте бота в группу, "
                "отправьте /create один раз, потом вернитесь в личку."
            )
            return
        await state.set_state(CreateEvent.group)
        await message.answer("Выберите группу:", reply_markup=group_picker_kb(accessible))
        return

    # /create в группе — регистрируем группу, отправляем ссылку в личку.
    if not await is_group_admin(message.bot, message.chat.id, message.from_user.id):
        await message.answer("Создавать встречи могут только администраторы.")
        return
    existing = await session.get(KnownGroup, message.chat.id)
    title = message.chat.title or "Группа"
    if existing is None:
        session.add(KnownGroup(chat_id=message.chat.id, title=title))
    else:
        existing.title = title
    await session.commit()
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start=create_{message.chat.id}"
    await message.answer(
        "Группа зарегистрирована. Продолжите в личке с ботом:",
        reply_markup=private_link_kb(link),
    )


@router.message(F.text.in_({"➕ Создать встречу", "создать встречу"}), StateFilter(None))
async def text_create(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await create_command(message, session=session, state=state)


@router.message(F.text.regexp(r"^/start(?:@\w+)? create_-?\d+$"))
async def deep_create(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Deep-link `create_<chat_id>` — продолжить создание в личке."""
    if message.chat.type != "private":
        await message.answer("Откройте ссылку в личном чате с ботом.")
        return
    try:
        chat_id = int(message.text.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await message.answer("Ссылка недействительна.")
        return
    known = await session.get(KnownGroup, chat_id)
    if known is None:
        await message.answer("Группа не найдена. Отправьте /create в группе.")
        return
    if not await is_group_admin(message.bot, chat_id, message.from_user.id):
        await message.answer("Вы не администратор этой группы.")
        return
    await state.update_data(source_chat_id=chat_id, source_chat_title=known.title)
    await state.set_state(CreateEvent.title)
    await message.answer("Название встречи? (3–100 символов):")


# ---------------------------------------------------------------------------
# Шаги FSM
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
        await query.answer("Группа не найдена. /create")
        await state.clear()
        return
    await state.update_data(source_chat_id=chat_id, source_chat_title=known.title)
    await state.set_state(CreateEvent.title)
    await query.answer()
    await query.message.edit_text("Название встречи? (3–100 символов):")


@router.message(CreateEvent.title)
async def step_title(message: Message, state: FSMContext) -> None:
    if await _handle_exit_intent(message, state):
        return
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
    if await _handle_exit_intent(message, state):
        return
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
    await query.message.edit_text(
        "Дата встречи: ДД.ММ.ГГ или ДД.ММ.ГГГГ (например, 30.10.26):"
    )


@router.message(CreateEvent.date)
async def step_date(message: Message, state: FSMContext) -> None:
    if await _handle_exit_intent(message, state):
        return
    value = message.text.strip()
    try:
        if len(value.split(".")) != 3:
            raise ValueError
        year_part = value.rsplit(".", 1)[-1]
        if len(year_part) == 2:
            d = datetime.strptime(value, "%d.%m.%y").date()
        elif len(year_part) == 4:
            d = datetime.strptime(value, "%d.%m.%Y").date()
        else:
            raise ValueError
    except ValueError:
        await message.answer("❌ Неверный формат. ДД.ММ.ГГ или ДД.ММ.ГГГГ (30.10.26).")
        return
    try:
        draft = EventDraft(event_date=d)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await state.update_data(event_date=draft.event_date)
    await state.set_state(CreateEvent.time)
    await message.answer("Время: ЧЧ:ММ или ЧЧ.ММ (19:00 или 19.00):")


@router.message(CreateEvent.time)
async def step_time(message: Message, state: FSMContext) -> None:
    if await _handle_exit_intent(message, state):
        return
    try:
        t = datetime.strptime(message.text.strip().replace(".", ":"), "%H:%M").time()
    except ValueError:
        await message.answer("Формат: ЧЧ:ММ или ЧЧ.ММ (19:00 / 19.00).")
        return
    data = await state.get_data()
    try:
        draft = EventDraft(event_date=data["event_date"], event_time=t)
    except DomainError as exc:
        await message.answer(exc.user_message)
        return
    await state.update_data(event_time=t)
    await state.set_state(CreateEvent.address)
    await message.answer("Адрес (Москва, метро/улица/дом):")


@router.message(CreateEvent.address)
async def step_address(message: Message, state: FSMContext) -> None:
    if await _handle_exit_intent(message, state):
        return
    value = message.text.strip()
    normalized, error = normalize_moscow_address(value)
    if error:
        await message.answer(error)
        return
    await state.update_data(address=normalized)
    await state.set_state(CreateEvent.conditions)
    await message.answer("Условия (например: 500 или 0 для бесплатной):")


@router.message(CreateEvent.conditions)
async def step_conditions(message: Message, state: FSMContext) -> None:
    if await _handle_exit_intent(message, state):
        return
    value = message.text.strip()
    if value == "0":
        value = "Бесплатно, без депозита"
    elif value.isdecimal():
        value = f"Депозит {value} ₽"
    if not 2 <= len(value) <= 500:
        await message.answer("Условия: 2–500 символов. Для бесплатной — 0.")
        return
    await state.update_data(conditions=value)
    await state.set_state(CreateEvent.capacity)
    await message.answer("Максимум участников (1–1000):")


@router.message(CreateEvent.capacity)
async def step_capacity(message: Message, state: FSMContext) -> None:
    if await _handle_exit_intent(message, state):
        return
    try:
        value = int(message.text.strip())
        draft = EventDraft(capacity=value)
    except (ValueError, DomainError) as exc:
        text = exc.user_message if isinstance(exc, DomainError) else "Введите число от 1 до 1000."
        await message.answer(text)
        return
    await state.update_data(capacity=draft.capacity)
    data = await state.get_data()
    has_group = data.get("source_chat_id") is not None
    await state.set_state(CreateEvent.visibility)
    await message.answer(
        "Кому будет видна встреча?",
        reply_markup=create_visibility_kb(has_group),
    )


@router.callback_query(CreateEvent.visibility, F.data.startswith("newvisibility:"))
async def step_visibility(query: CallbackQuery, state: FSMContext) -> None:
    visibility = query.data.split(":", 1)[1]
    if visibility not in {"chat", "public"}:
        await query.answer("Неверный выбор.", show_alert=True)
        return
    data = await state.get_data()
    if visibility == "chat" and data.get("source_chat_id") is None:
        await query.answer("Сначала выберите группу командой /create.", show_alert=True)
        return
    await state.update_data(visibility=visibility)
    await state.set_state(CreateEvent.photo)
    await query.answer()
    await query.message.answer(
        "📸 Загрузите фото встречи или нажмите «Пропустить».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏭ Пропустить", callback_data="newphoto:skip")
        ]]),
    )


@router.message(CreateEvent.photo, F.photo)
async def step_photo(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if await _handle_exit_intent(message, state):
        return
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await save_new_event(message, state, session)


@router.message(CreateEvent.photo)
async def step_photo_invalid(message: Message, state: FSMContext) -> None:
    if await _handle_exit_intent(message, state):
        return
    await message.answer(
        "Отправьте фотографию или нажмите «⏭ Пропустить».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏭ Пропустить", callback_data="newphoto:skip")
        ]]),
    )


@router.callback_query(CreateEvent.photo, F.data == "newphoto:skip")
async def step_photo_skip(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await query.answer()
    await state.update_data(photo_file_id="")
    await save_new_event(query.message, state, session)


# ---------------------------------------------------------------------------
# Финальное сохранение + публикация карточки в группу
# ---------------------------------------------------------------------------


async def save_new_event(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Собрать draft, создать событие, опубликовать карточку в группе."""
    from app.routers.events import send_event_card

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
            visibility=data["visibility"],
            source_chat_id=data.get("source_chat_id"),
            source_chat_title=data.get("source_chat_title", ""),
            photo_file_id=data.get("photo_file_id", ""),
        )
    except (KeyError, DomainError) as exc:
        text = exc.user_message if isinstance(exc, DomainError) else "Не хватает данных. Начните заново: /create"
        await message.answer(text)
        await state.clear()
        return

    service = EventService(session)
    try:
        view = await service.create(draft, owner_id=message.from_user.id)
    except DomainError as exc:
        await message.answer(exc.user_message)
        await state.clear()
        return
    except Exception:
        logger.exception("create_failed")
        await message.answer("Не удалось создать встречу. Попробуйте позже.")
        await state.clear()
        return

    await session.commit()
    await state.clear()

    await message.answer(
        f"✅ Встреча создана: «{view.title}»\n"
        f"📅 {view.starts_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"👥 {view.capacity} мест"
    )

    # Публикация карточки в исходную группу + pin.
    if view.source_chat_id is not None:
        event = await session.get(Event, view.id)
        if event is None:
            return
        try:
            sent = await send_event_card(
                message,
                session,
                event,
                private_details=True,
                viewer_id=None,
                chat_id=view.source_chat_id,
            )
        except TelegramError as exc:
            logger.warning("publish_failed", event_id=view.id, error=str(exc))
            return
        except TypeError:
            # Если send_event_card ещё не поддерживает chat_id — не роняем создание.
            logger.exception("send_event_card_missing_chat_id")
            await message.answer(
                "⚠️ Встреча сохранена, но карточку в группу отправить не удалось "
                "(send_event_card не поддерживает chat_id)."
            )
            return
        try:
            await message.bot.pin_chat_message(
                chat_id=sent.chat.id,
                message_id=sent.message_id,
                disable_notification=True,
            )
        except TelegramError as exc:
            logger.warning("pin_failed", event_id=view.id, error=str(exc))
        await session.commit()