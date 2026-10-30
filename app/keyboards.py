"""Фабрики клавиатур. InlineKeyboardMarkup/ReplyKeyboardMarkup.

Все клавиатуры — чистые фабрики: принимают id/флаги, возвращают markup.
Не знают про БД, сервисы и Telegram-объекты (кроме типов aiogram).
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.db import Event
from app.labels import CATEGORY_LABELS


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Афиша встреч"), KeyboardButton(text="➕ Создать встречу")],
            [KeyboardButton(text="📋 Мои встречи"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def scope_menu(chat_id: int | None = None) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    if chat_id is not None:
        buttons.append([InlineKeyboardButton(
            text="🏠 Встречи нашего чата",
            callback_data=f"scope:chat:{chat_id}:-",
        )])
    buttons.append([InlineKeyboardButton(
        text="🌍 Все встречи Москвы", callback_data="scope:public:-"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def dates_kb(scope_token: str, dates: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(dates), 2):
        row = []
        for iso in dates[i:i + 2]:
            d = iso.split("-")
            label = f"{d[2]}.{d[1]}.{d[0]}"
            row.append(InlineKeyboardButton(
                text=label, callback_data=f"pickdate:{scope_token}:{iso}",
            ))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_kb(scope_token: str, day_iso: str, counts: dict[str, int]) -> InlineKeyboardMarkup:
    items = [(slug, count) for slug, count in counts.items() if slug in CATEGORY_LABELS]
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(items), 2):
        row = []
        for slug, count in items[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=f"{CATEGORY_LABELS[slug]} ({count})",
                callback_data=f"category:{scope_token}:{day_iso}:{slug}:0",
            ))
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pagination_kb(
    scope_token: str, day_iso: str, category: str, page: int, has_next: bool
) -> InlineKeyboardMarkup | None:
    if not has_next:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Далее",
            callback_data=f"page:{scope_token}:{day_iso}:{category}:{page + 1}",
        )
    ]])


def event_kb(
    event: Event,
    booked: int,
    viewer_id: int | None = None,
    *,
    show_detail: bool = True,
    show_actions: bool = True,
) -> InlineKeyboardMarkup:
    event_id = event.id
    available = event.capacity - booked

    if not show_actions:
        # после начала — только «Удалить» владельцу
        rows: list[list[InlineKeyboardButton]] = []
        if viewer_id is not None and viewer_id == event.owner_id:
            rows.append([InlineKeyboardButton(
                text="🗑 Удалить встречу", callback_data=f"deleteask:{event_id}"
            )])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    if available > 0:
        join_text, join_cb = "Записаться", f"join:{event_id}"
    else:
        join_text, join_cb = "Мест нет", f"full:{event_id}"

    top_row: list[InlineKeyboardButton] = []
    if show_detail:
        top_row.append(InlineKeyboardButton(text="Подробнее", callback_data=f"detail:{event_id}"))
    top_row.append(InlineKeyboardButton(text=join_text, callback_data=join_cb))

    rows = [
        top_row,
        [
            InlineKeyboardButton(text="👥 Участники", callback_data=f"participants:{event_id}"),
            InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancel:{event_id}"),
        ],
    ]
    if viewer_id is not None and viewer_id == event.owner_id:
        rows.append([InlineKeyboardButton(text="🗑 Удалить встречу", callback_data=f"deleteask:{event_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_event_url_kb(bot_username: str, event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="📌 Открыть встречу в боте",
            url=f"https://t.me/{bot_username}?start=event_{event_id}",
        )
    ]])


def create_category_kb() -> InlineKeyboardMarkup:
    items = list(CATEGORY_LABELS.items())
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(text=label, callback_data=f"newcat:{slug}")
            for slug, label in items[i:i + 2]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_visibility_kb(has_group: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if has_group:
        rows.append([InlineKeyboardButton(text="🏠 Для нашего чата", callback_data="newvisibility:chat")])
    rows.append([InlineKeyboardButton(text="🌍 Для всех", callback_data="newvisibility:public")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_picker_kb(groups: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"🏠 {title[:45]}", callback_data=f"newgroup:{chat_id}")]
        for chat_id, title in groups
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def private_link_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть личный чат", url=url)
    ]])


def mine_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"editmenu:{event_id}")],
        [InlineKeyboardButton(text="👥 Управлять участниками", callback_data=f"managepeople:{event_id}")],
        [InlineKeyboardButton(text="🗑 Удалить встречу", callback_data=f"deleteask:{event_id}")],
    ])


def edit_menu_kb(event_id: int) -> InlineKeyboardMarkup:
    fields = [
        ("title", "Название"),
        ("description", "Описание"),
        ("category", "Категория"),
        ("date", "Дата"),
        ("time", "Время"),
        ("address", "Адрес"),
        ("conditions", "Условия"),
        ("capacity", "Количество мест"),
    ]
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"editfield:{event_id}:{field}")]
        for field, label in fields
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_delete_kb(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, удалить", callback_data=f"deleteconfirm:{event_id}"),
        InlineKeyboardButton(text="Нет", callback_data=f"deletecancel:{event_id}"),
    ]])


def participants_kb(
    event_id: int,
    participants: list[tuple[int, str]],
    *,
    page: int = 0,
    total: int = 1,
) -> InlineKeyboardMarkup:
    """Список участников с пагинацией (см. ``mine.py::PAGE_SIZE = 8``).

    ``page``/``total`` — для кнопок ⬅️/➡️. При ``total=1`` стрелок нет.
    """
    rows = [
        [InlineKeyboardButton(
            text=f"❌ {name[:45]}",
            callback_data=f"kickask:{event_id}:{uid}",
        )]
        for uid, name in participants
    ]
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="⬅️", callback_data=f"managepeople:{event_id}:{page - 1}"
        ))
    if page + 1 < total:
        nav.append(InlineKeyboardButton(
            text="➡️", callback_data=f"managepeople:{event_id}:{page + 1}"
        ))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="← Назад", callback_data=f"detail:{event_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)