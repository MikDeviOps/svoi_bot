"""Управление встречами: редактирование (FSM), удаление, участники, исключения."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Event, EventExclusion, EventMessage, ParticipantDirectory, Signup
from app.keyboards.common import CATEGORIES, EDIT_FIELDS, PRIVATE_MENU
from app.services.events import (
    DELETED_TEXT,
    archive_event_messages,
    event_with_count,
    refresh_event_messages,
)
from app.states import EditEvent
from app.utils.html import safe_html
from app.utils.time import now_msk

logger = logging.getLogger(__name__)

router = Router(name="management")

PRIVATE_ONLY = "Управление встречей доступно только в личке с ботом."
NO_RIGHTS = "Вы не организатор этой встречи или встреча удалена."
PAGE_SIZE = 8
LIST_PREVIEW = 30

# Поля EDIT_FIELDS → колонки ORM. date/time живут в одном starts_at.
DIRECT_FIELDS = {"title", "description", "address", "conditions", "capacity"}
TEXT_LIMITS = {
    "title": (3, 100),
    "description": (0, 1000),
    "address": (5, 250),
    "conditions": (2, 500),
}
HINTS = {
    "date": "ДД.ММ.ГГГГ",
    "time": "ЧЧ:ММ (Москва)",
    "capacity": "число от 1 до 1000",
    "title": "от 3 до 100 символов",
    "description": "до 1000 символов, «-» — очистить",
    "address": "от 5 до 250 символов",
    "conditions": "от 2 до 500 символов",
}


# --------------------------------------------------------------------------- #
# Хелперы
# --------------------------------------------------------------------------- #
async def _guard_private(callback: CallbackQuery) -> bool:
    if callback.message is None or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer(PRIVATE_ONLY, show_alert=True)
        return False
    return True


def _ints(data: str, count: int, start: int = 1) -> list[int] | None:
    parts = data.split(":")
    if len(parts) < start + count:
        return None
    try:
        return [int(p) for p in parts[start:start + count]]
    except ValueError:
        return None


async def _managed_event(
    session: AsyncSession,
    event_id: int,
    user_id: int,
) -> tuple[dict | None, str | None]:
    """Встреча + проверка прав (организатор или владелец платформы)."""
    event = await event_with_count(session, event_id)
    if event is None:
        return None, "Встреча уже удалена или не найдена."
    if event["owner_id"] != user_id and user_id not in settings.owners:
        return None, NO_RIGHTS
    return event, None


def _is_owner(user_id: int) -> bool:
    return user_id in settings.owners


async def _lock_event(session: AsyncSession, event_id: int) -> Event | None:
    """Блокировка строки встречи для критичных изменений (capacity/kick)."""
    stmt = select(Event).where(Event.id == event_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Меню редактирования
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("editmenu:"))
async def cb_edit_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parsed = _ints(callback.data, 1)
    if not parsed:
        await callback.message.answer("Неверный номер встречи.")
        return
    event_id = parsed[0]

    event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    await state.clear()
    keyboard = [
        [InlineKeyboardButton(text=label, callback_data=f"editfield:{event_id}:{field}")]
        for field, label in EDIT_FIELDS.items()
    ]
    keyboard.append([InlineKeyboardButton(text="❌ Закрыть", callback_data=f"editclose:{event_id}")])

    await callback.message.answer(
        f"✏️ Что изменить в встрече «{safe_html(event['title'])}»?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )


@router.callback_query(F.data.startswith("editclose:"))
async def cb_edit_close(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Закрыто")
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Редактирование: старт
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("editfield:"))
async def cb_start_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.message.answer("Неверный формат.")
        return
    try:
        event_id = int(parts[1])
    except ValueError:
        await callback.message.answer("Неверный номер встречи.")
        return
    field = parts[2]

    if field not in EDIT_FIELDS:
        await callback.message.answer("Неизвестное поле.")
        return

    event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    await state.clear()

    if field == "category":
        keyboard = [
            [InlineKeyboardButton(text=name, callback_data=f"editcat:{event_id}:{key}")]
            for key, name in CATEGORIES.items()
        ]
        await callback.message.answer(
            "Выберите категорию:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        )
        return

    await state.set_state(EditEvent.value)
    await state.update_data(edit_event_id=event_id, edit_field=field)
    await callback.message.answer(
        f"Введите новое значение: <b>{safe_html(EDIT_FIELDS[field])}</b>\n"
        f"Подсказка: {HINTS.get(field, 'текст')}\n\n"
        "/cancel — отмена",
    )


# --------------------------------------------------------------------------- #
# Редактирование: категория
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("editcat:"))
async def cb_edit_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        return
    try:
        event_id = int(parts[1])
    except ValueError:
        return
    category = parts[2]
    if category not in CATEGORIES:
        await callback.message.answer("Неизвестная категория.")
        return

    event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    locked = await _lock_event(session, event_id)
    if locked is None:
        await callback.message.answer("Встреча уже удалена.")
        return
    locked.category = category

    await session.commit()
    await state.clear()
    await refresh_event_messages(bot, event_id)

    await callback.message.answer(f"✅ Категория изменена: {CATEGORIES[category]}")


# --------------------------------------------------------------------------- #
# Редактирование: ввод значения (FSM)
# --------------------------------------------------------------------------- #
def _convert_value(
    event_obj: Event,
    field: str,
    raw: str,
    booked: int,
) -> tuple[str, object]:
    """Возвращает (колонка, значение). Бросает ValueError с текстом для пользователя."""
    now = now_msk()
    local_dt = event_obj.starts_at.astimezone(settings.tzinfo)
    value = raw.strip()

    if field == "date":
        try:
            d = datetime.strptime(value, "%d.%m.%Y").date()
        except ValueError:
            raise ValueError("Формат даты: ДД.ММ.ГГГГ.")
        if not (now.date() <= d <= (now + timedelta(days=365)).date()):
            raise ValueError("Дата должна быть в пределах следующего года.")
        new_dt = datetime.combine(d, local_dt.timetz().replace(tzinfo=None), tzinfo=settings.tzinfo)
        if new_dt <= now:
            raise ValueError("Встреча должна быть в будущем.")
        return "starts_at", new_dt

    if field == "time":
        try:
            t = datetime.strptime(value, "%H:%M").time()
        except ValueError:
            raise ValueError("Формат времени: ЧЧ:ММ.")
        new_dt = datetime.combine(local_dt.date(), t, tzinfo=settings.tzinfo)
        if new_dt <= now:
            raise ValueError("Встреча должна быть в будущем.")
        return "starts_at", new_dt

    if field == "capacity":
        try:
            cap = int(value)
        except ValueError:
            raise ValueError("Вместимость — целое число.")
        if not (1 <= cap <= 1000):
            raise ValueError("Вместимость должна быть от 1 до 1000.")
        if cap < booked:
            raise ValueError(f"Мест не может быть меньше числа записанных ({booked}).")
        return "capacity", cap

    if field in TEXT_LIMITS:
        if field == "description" and value == "-":
            value = ""
        low, high = TEXT_LIMITS[field]
        if not (low <= len(value) <= high):
            raise ValueError(f"Длина текста: от {low} до {high} символов.")
        # TODO: вернуть normalize_moscow_address из locations.py для field == "address"
        return field, value

    raise ValueError("Это поле нельзя изменить.")


@router.message(StateFilter(EditEvent.value), Command("cancel"))
async def cmd_cancel_edit(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Редактирование отменено.", reply_markup=PRIVATE_MENU)


@router.message(StateFilter(EditEvent.value), F.text, ~F.text.startswith("/"))
async def receive_edit(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    event_id = data.get("edit_event_id")
    field = data.get("edit_field")

    if not event_id or not field:
        await state.clear()
        await message.answer("Сессия редактирования истекла. Откройте встречу заново: /mine")
        return

    # Блокируем строку и считаем записанных в той же транзакции.
    locked = await _lock_event(session, int(event_id))
    if locked is None:
        await state.clear()
        await message.answer("Встреча уже удалена.")
        return

    if locked.owner_id != message.from_user.id and not _is_owner(message.from_user.id):
        await state.clear()
        await message.answer(NO_RIGHTS)
        return

    booked = int(
        (await session.execute(select(func.count(Signup.id)).where(Signup.event_id == locked.id))).scalar() or 0
    )

    try:
        column, value = _convert_value(locked, field, message.text or "", booked)
    except ValueError as exc:
        await message.answer(f"❗ {exc}\nПопробуйте ещё раз или /cancel.")
        return

    setattr(locked, column, value)
    await session.commit()
    await state.clear()

    await refresh_event_messages(bot, locked.id)
    await message.answer(
        "✅ Встреча обновлена. Карточки в чатах тоже обновлены.",
        reply_markup=PRIVATE_MENU,
    )


@router.message(StateFilter(EditEvent.value))
async def receive_edit_invalid(message: Message):
    await message.answer("Пришлите новое значение текстом или отмените: /cancel")


# --------------------------------------------------------------------------- #
# Удаление встречи
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("deleteask:"))
async def cb_delete_ask(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parsed = _ints(callback.data, 1)
    if not parsed:
        await callback.message.answer("Неверный номер встречи.")
        return
    event_id = parsed[0]

    event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    await callback.message.answer(
        f"Удалить встречу «{safe_html(event['title'])}»?\n"
        f"Записи участников ({event['booked']}) тоже будут удалены.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"deleteconfirm:{event_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"deletecancel:{event_id}"),
        ]]),
    )


@router.callback_query(F.data.startswith("deleteconfirm:"))
async def cb_delete_confirm(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parsed = _ints(callback.data, 1)
    if not parsed:
        await callback.message.answer("Неверный номер встречи.")
        return
    event_id = parsed[0]

    event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    targets = [
        (row.chat_id, row.message_id)
        for row in (
            await session.execute(select(EventMessage).where(EventMessage.event_id == event_id))
        ).scalars().all()
    ]

    stmt = delete(Event).where(Event.id == event_id)
    if not _is_owner(callback.from_user.id):
        stmt = stmt.where(Event.owner_id == callback.from_user.id)
    result = await session.execute(stmt)
    await session.commit()

    if result.rowcount == 0:
        await callback.message.answer("Встреча уже удалена.")
        return

    await archive_event_messages(bot, targets, DELETED_TEXT)
    await callback.message.answer("Встреча удалена.", reply_markup=PRIVATE_MENU)


@router.callback_query(F.data.startswith("deletecancel:"))
async def cb_delete_cancel(callback: CallbackQuery):
    await callback.answer("Отменено")
    if not await _guard_private(callback):
        return
    await callback.message.answer("Удаление отменено.")


# --------------------------------------------------------------------------- #
# Управление участниками (рендер)
# --------------------------------------------------------------------------- #
async def _render_manage_participants(
    target: Message,
    session: AsyncSession,
    event_id: int,
    page: int = 0,
) -> None:
    """Страница управления участниками. Права проверяет вызывающий хендлер.

    Используется и из management.py, и из admin.py (adminpeople:).
    """
    event = await event_with_count(session, event_id)
    if event is None:
        await target.answer("Встреча не найдена.")
        return

    people = (
        await session.execute(
            select(Signup.user_id, Signup.telegram_name)
            .where(Signup.event_id == event_id)
            .order_by(Signup.created_at, Signup.user_id)
        )
    ).all()

    excluded = (
        await session.execute(
            select(
                EventExclusion.user_id,
                func.coalesce(
                    func.nullif(ParticipantDirectory.display_name, ""),
                    func.cast(EventExclusion.user_id, __import__("sqlalchemy").Text),
                ).label("name"),
            )
            .outerjoin(ParticipantDirectory, ParticipantDirectory.user_id == EventExclusion.user_id)
            .where(EventExclusion.event_id == event_id)
            .order_by(EventExclusion.excluded_at.desc())
        )
    ).all()

    rows: list[tuple[str, int, str]] = [
        ("active", uid, name or str(uid)) for uid, name in people
    ]
    rows += [("excluded", uid, name or str(uid)) for uid, name in excluded]

    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(0, page), pages - 1)
    window = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    keyboard: list[list[InlineKeyboardButton]] = []
    for kind, uid, name in window:
        action = "kickask" if kind == "active" else "restoreask"
        prefix = "🚫" if kind == "active" else "✅"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{prefix} {name[:28]}",
                callback_data=f"{action}:{event_id}:{uid}",
            )
        ])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"managepeople:{event_id}:{page - 1}"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"managepeople:{event_id}:{page + 1}"))
    if nav:
        keyboard.append(nav)

    lines = [
        f"👥 Участники встречи «{safe_html(event['title'])}»",
        f"Записано: {event['booked']}/{event['capacity']} · страниц: {page + 1}/{pages}",
        "",
    ]
    lines += [f"👤 {safe_html(name or uid)}" for uid, name in people[:LIST_PREVIEW]] or ["Пока никто не записался."]
    lines += ["", f"🚫 Исключённые ({len(excluded)}):"]
    lines += [f"🚫 {safe_html(name)}" for uid, name in excluded[:LIST_PREVIEW]] or ["Нет исключённых."]
    if len(people) > LIST_PREVIEW or len(excluded) > LIST_PREVIEW:
        lines.append(f"Показаны первые {LIST_PREVIEW} имён; кнопки — по страницам.")

    await target.answer(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None,
    )


@router.callback_query(F.data.startswith("managepeople:"))
async def cb_manage_people(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parts = callback.data.split(":")
    parsed = _ints(callback.data, 1)
    if not parsed:
        await callback.message.answer("Неверный формат.")
        return
    event_id = parsed[0]
    page = 0
    if len(parts) > 2 and parts[2].isdigit():
        page = int(parts[2])

    _event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    await _render_manage_participants(callback.message, session, event_id, page)


# --------------------------------------------------------------------------- #
# Исключение участника
# --------------------------------------------------------------------------- #
async def _person_name(session: AsyncSession, event_id: int, user_id: int) -> str:
    name = (
        await session.execute(
            select(Signup.telegram_name).where(
                Signup.event_id == event_id, Signup.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if name:
        return name
    name = (
        await session.execute(
            select(ParticipantDirectory.display_name).where(ParticipantDirectory.user_id == user_id)
        )
    ).scalar_one_or_none()
    return name or str(user_id)


@router.callback_query(F.data.startswith("kickask:"))
async def cb_kick_ask(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parsed = _ints(callback.data, 2)
    if not parsed:
        await callback.message.answer("Неверный формат.")
        return
    event_id, user_id = parsed

    _event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    exists = (
        await session.execute(
            select(Signup.id).where(Signup.event_id == event_id, Signup.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not exists:
        await callback.message.answer("Участник уже не записан.")
        return

    name = await _person_name(session, event_id, user_id)
    await callback.message.answer(
        f"Удалить участника {safe_html(name)} из встречи?\n"
        "Место освободится, повторная запись будет запрещена.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"kickconfirm:{event_id}:{user_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"kickcancel:{event_id}:{user_id}"),
        ]]),
    )


@router.callback_query(F.data.startswith("kickconfirm:"))
async def cb_kick_confirm(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parsed = _ints(callback.data, 2)
    if not parsed:
        await callback.message.answer("Неверный формат.")
        return
    event_id, user_id = parsed

    _event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    locked = await _lock_event(session, event_id)
    if locked is None:
        await callback.message.answer("Встреча уже удалена.")
        return

    name = await _person_name(session, event_id, user_id)

    # Идемпотентно: повторный клик не упадёт на составном PK.
    await session.execute(
        pg_insert(EventExclusion)
        .values(
            event_id=event_id,
            user_id=user_id,
            excluded_at=now_msk(),
            excluded_by=callback.from_user.id,
        )
        .on_conflict_do_nothing(index_elements=["event_id", "user_id"])
    )
    result = await session.execute(
        delete(Signup).where(Signup.event_id == event_id, Signup.user_id == user_id)
    )
    await session.commit()

    if result.rowcount == 0:
        await callback.message.answer("Участник уже удалён.")
        return

    await refresh_event_messages(bot, event_id)
    await callback.message.answer(
        f"✅ {safe_html(name)} исключён из встречи. "
        "Повторная запись запрещена, место освобождено."
    )


@router.callback_query(F.data.startswith("kickcancel:"))
async def cb_kick_cancel(callback: CallbackQuery):
    await callback.answer("Отменено")
    if not await _guard_private(callback):
        return
    await callback.message.answer("Удаление отменено.")


# --------------------------------------------------------------------------- #
# Возврат доступа
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("restoreask:"))
async def cb_restore_ask(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parsed = _ints(callback.data, 2)
    if not parsed:
        await callback.message.answer("Неверный формат.")
        return
    event_id, user_id = parsed

    _event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    excluded = (
        await session.execute(
            select(EventExclusion.user_id).where(
                EventExclusion.event_id == event_id, EventExclusion.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if not excluded:
        await callback.message.answer("Этот пользователь уже не в списке исключённых.")
        return

    name = await _person_name(session, event_id, user_id)
    await callback.message.answer(
        f"Вернуть доступ к встрече для {safe_html(name)}?\n"
        "Пользователь сможет записаться самостоятельно.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Вернуть доступ", callback_data=f"restoreconfirm:{event_id}:{user_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"restorecancel:{event_id}:{user_id}"),
        ]]),
    )


@router.callback_query(F.data.startswith("restoreconfirm:"))
async def cb_restore_confirm(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if not await _guard_private(callback):
        return

    parsed = _ints(callback.data, 2)
    if not parsed:
        await callback.message.answer("Неверный формат.")
        return
    event_id, user_id = parsed

    _event, error = await _managed_event(session, event_id, callback.from_user.id)
    if error:
        await callback.message.answer(error)
        return

    name = await _person_name(session, event_id, user_id)
    result = await session.execute(
        delete(EventExclusion).where(
            EventExclusion.event_id == event_id, EventExclusion.user_id == user_id
        )
    )
    await session.commit()

    if result.rowcount == 0:
        await callback.message.answer("Этот пользователь уже не в списке исключённых.")
        return

    await callback.message.answer(
        f"✅ {safe_html(name)} снова может записаться на эту встречу. "
        "Автоматически место не занято."
    )


@router.callback_query(F.data.startswith("restorecancel:"))
async def cb_restore_cancel(callback: CallbackQuery):
    await callback.answer("Отменено")
    if not await _guard_private(callback):
        return
    await callback.message.answer("Возврат доступа отменён.")


# --------------------------------------------------------------------------- #
# Мелкие callback-и карточки
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("full:"))
async def cb_full(callback: CallbackQuery):
    await callback.answer("На эту встречу уже нет свободных мест.", show_alert=True)


@router.callback_query(F.data.startswith("detail:"))
async def cb_detail(callback: CallbackQuery):
    await callback.answer("Вся информация уже указана в карточке встречи.", show_alert=True)