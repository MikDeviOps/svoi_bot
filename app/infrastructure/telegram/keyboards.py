# app/infrastructure/telegram/keyboards.py
from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions

from app.domain.models import Event, Signup, EventExclusion


def event_keyboard(event: Event, booked: int, *, viewer_id: int | None) -> InlineKeyboardMarkup:
    available = event.capacity - booked
    join_label = "Записаться" if available > 0 else "Мест нет"
    join_action = f"join:{event.id}" if available > 0 else f"full:{event.id}"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=join_label, callback_data=join_action)],
        [
            InlineKeyboardButton(text="👥 Участники", callback_data=f"participants:{event.id}"),
            InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancel:{event.id}"),
        ],
    ]
    if viewer_id is not None and viewer_id == event.owner_id:
        rows.append([
            InlineKeyboardButton(text="🗑 Удалить встречу", callback_data=f"deleteask:{event.id}"),
            InlineKeyboardButton(text="👥 Управление", callback_data=f"managepeople:{event.id}:0"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manage_people_keyboard(
    event_id: int,
    active: list[Signup],
    excluded: list[EventExclusion],
    page: int,
    pages: int,
) -> InlineKeyboardMarkup:
    page_size = 8
    rows: list[list[InlineKeyboardButton]] = []
    all_items: list[tuple[str, int, str]] = []
    all_items += [("kickask", s.user_id, s.telegram_name or str(s.user_id)) for s in active]
    all_items += [("restoreask", e.user_id, str(e.user_id)) for e in excluded]
    for kind, uid, name in all_items[page * page_size : (page + 1) * page_size]:
        prefix = "🚫 Исключить" if kind == "kickask" else "✅ Вернуть доступ"
        rows.append([
            InlineKeyboardButton(
                text=f"{prefix}: {name[:26]}",
                callback_data=f"{kind}:{event_id}:{uid}",
            )
        ])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"managepeople:{event_id}:{page - 1}"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"managepeople:{event_id}:{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_keyboard(*, invite_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Вступить в группу", url=invite_url)],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="support:verify")],
        ]
    )


def delete_ask_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"deleteyes:{event_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"deleteno:{event_id}"),
            ]
        ]
    )


def organizer_profile_keyboard(owner_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👥 Список участников",
                    callback_data=f"org:people:{owner_id}:{page}:0",
                ),
                InlineKeyboardButton(text="◀️ К списку", callback_data=f"org:list:{page}"),
            ]
        ]
    )


def organizer_people_keyboard(
    owner_id: int, origin_page: int, people_page: int, total: int
) -> InlineKeyboardMarkup:
    page_size = 15
    buttons: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if people_page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️",
                callback_data=f"org:people:{owner_id}:{origin_page}:{people_page - 1}",
            )
        )
    if (people_page + 1) * page_size < total:
        nav.append(
            InlineKeyboardButton(
                text="▶️",
                callback_data=f"org:people:{owner_id}:{origin_page}:{people_page + 1}",
            )
        )
    if nav:
        buttons.append(nav)
    buttons.append([
        InlineKeyboardButton(
            text="◀️ К организатору",
            callback_data=f"org:profile:{owner_id}:{origin_page}",
        )
    ])
    buttons.append([
        InlineKeyboardButton(text="📋 К списку", callback_data=f"org:list:{origin_page}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def organizers_keyboard(
    rows: list[tuple[int, str, str, int]], page: int, total: int
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for owner_id, name, username, total_events in rows:
        if name:
            label = name[:35]
        elif username:
            label = f"@{username}"[:35]
        else:
            label = str(owner_id)[:35]
        buttons.append([
            InlineKeyboardButton(
                text=f"👤 {label} · {total_events} встреч",
                callback_data=f"org:profile:{owner_id}:{page}",
            )
        ])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"org:list:{page - 1}"))
    if (page + 1) * 8 < total:
        nav.append(InlineKeyboardButton(text="Далее ▶️", callback_data=f"org:list:{page + 1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def private_chat_keyboard(bot_username: str, action: str, event_id: int) -> InlineKeyboardMarkup:
    link = f"https://t.me/{bot_username}?start={action}_{event_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть личный чат", url=link)]]
    )


def link_preview_disabled() -> LinkPreviewOptions:
    return LinkPreviewOptions(is_disabled=True)