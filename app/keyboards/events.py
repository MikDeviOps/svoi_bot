"""Клавиатуры карточек встреч — компактные и логичные."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings


def event_keyboard(event: dict, user_id: int | None = None) -> InlineKeyboardMarkup:
    event_id = event["id"]
    free = max(0, event["capacity"] - event["booked"])
    is_owner = user_id and (event["owner_id"] == user_id or user_id in settings.owners)
    
    buttons = []
    
    # 1. Главное действие (Запись)
    if free > 0:
        buttons.append([
            InlineKeyboardButton(text=f"✍️ Записаться ({free} мест)", callback_data=f"join:{event_id}", style="success")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="🚫 Мест нет", callback_data=f"full:{event_id}", style="danger")
        ])
    
    # 2. Информационные кнопки
    buttons.append([
        InlineKeyboardButton(text="👥 Участники", callback_data=f"participants:{event_id}", style="primary")
    ])
    buttons.append([
        InlineKeyboardButton(text="🔗 Поделиться", switch_inline_query=f"event_{event_id}")
    ])
    
    # 3. Блок управления (только для организатора/владельца)
    if is_owner:
        # Размещаем "Отменить" и "Удалить" РЯДОМ в одной строке для экономии места
        buttons.append([
            InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancel:{event_id}", style="danger"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"deleteask:{event_id}", style="danger")
        ])
        # Инструменты управления тоже рядом
        buttons.append([
            InlineKeyboardButton(text="✏️ Изменить", callback_data=f"editmenu:{event_id}", style="primary"),
            InlineKeyboardButton(text="⚙️ Участники", callback_data=f"managepeople:{event_id}:0", style="primary")
        ])
    else:
        # Для обычного пользователя кнопка отмены одна, во всю ширину
        buttons.append([
            InlineKeyboardButton(text="❌ Отменить мою запись", callback_data=f"cancel:{event_id}", style="danger")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def private_event_keyboard(event: dict, user_id: int | None = None) -> InlineKeyboardMarkup:
    """Клавиатура для личного чата."""
    return event_keyboard(event, user_id)


def group_event_keyboard(event: dict) -> InlineKeyboardMarkup:
    """Клавиатура для группового чата (без персональных кнопок управления)."""
    return event_keyboard(event, None)