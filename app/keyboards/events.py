"""Клавиатуры карточек встреч."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings

BOOKING_OPEN = "join"
BOOKING_FULL = "full"


def _can_manage(event: dict, user_id: int | None) -> bool:
    if user_id is None:
        return False
    return event["owner_id"] == user_id or user_id in settings.owners


def event_keyboard(
    event: dict,
    user_id: int | None = None,
    *,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup:
    """Клавиатура карточки встречи.

    В группе user_id можно не передавать — тогда показываем только
    публичные действия. В личке передаём user_id, чтобы организатор
    увидел кнопки управления.
    """
    event_id = event["id"]
    free = max(0, event["capacity"] - event["booked"])

    if free > 0:
        first = InlineKeyboardButton(
            text=f"✍️ Записаться ({free})", callback_data=f"join:{event_id}"
        )
    else:
        first = InlineKeyboardButton(
            text="🚫 Мест нет", callback_data=f"{BOOKING_FULL}:{event_id}"
        )

    rows: list[list[InlineKeyboardButton]] = [
        [first, InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancel:{event_id}")],
        [InlineKeyboardButton(text="👥 Участники", callback_data=f"participants:{event_id}")],
    ]

    if bot_username:
        rows.append([
            InlineKeyboardButton(
                text="🔗 Открыть в личке",
                url=f"https://t.me/{bot_username}?start=event_{event_id}",
            )
        ])

    if _can_manage(event, user_id):
        rows.append([
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"editmenu:{event_id}"),
            InlineKeyboardButton(text="👥 Управление", callback_data=f"managepeople:{event_id}:0"),
        ])
        rows.append([
            InlineKeyboardButton(text="🗑 Удалить встречу", callback_data=f"deleteask:{event_id}")
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def private_event_keyboard(
    event: dict,
    user_id: int | None = None,
    *,
    bot_username: str | None = None,
) -> InlineKeyboardMarkup:
    """Клавиатура карточки в личном чате."""
    return event_keyboard(event, user_id, bot_username=bot_username)


def group_event_keyboard(event: dict, *, bot_username: str | None = None) -> InlineKeyboardMarkup:
    """Клавиатура карточки в групповом чате (без персональных кнопок)."""
    return event_keyboard(event, None, bot_username=bot_username)