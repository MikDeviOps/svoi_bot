"""Клавиатуры карточек встреч — компактный одноколоночный вид с цветами (Bot API 9.4+)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings


def event_keyboard(event: dict, user_id: int | None = None) -> InlineKeyboardMarkup:
    """
    Компактная клавиатура карточки встречи в один столбик.
    Используем новые цвета кнопок из Bot API 9.4:
    - "success" (🟢 зелёная) для позитивных действий
    - "danger" (🔴 красная) для отмены/удаления
    - "primary" (🔵 синяя) для основных навигационных действий
    """
    event_id = event["id"]
    free = max(0, event["capacity"] - event["booked"])
    
    buttons = []
    
    # 1. Кнопка записи (зелёная) или "Мест нет" (красная)
    if free > 0:
        buttons.append([
            InlineKeyboardButton(
                text=f"✍️ Записаться ({free} мест)",
                callback_data=f"join:{event_id}",
                style="success"
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text="🚫 Мест нет",
                callback_data=f"full:{event_id}",
                style="danger"
            )
        ])
    
    # 2. Кнопка отмены записи (красная)
    buttons.append([
        InlineKeyboardButton(
            text="❌ Отменить запись",
            callback_data=f"cancel:{event_id}",
            style="danger"
        )
    ])
    
    # 3. Кнопка участников (синяя)
    buttons.append([
        InlineKeyboardButton(
            text="👥 Участники",
            callback_data=f"participants:{event_id}",
            style="primary"
        )
    ])
    
    # 4. Кнопка поделиться (стандартная)
    buttons.append([
        InlineKeyboardButton(
            text="🔗 Поделиться",
            switch_inline_query=f"event_{event_id}"
        )
    ])
    
    # 5. Кнопки управления (только для организатора или владельца)
    if user_id and (event["owner_id"] == user_id or user_id in settings.owners):
        buttons.append([
            InlineKeyboardButton(
                text="✏️ Редактировать",
                callback_data=f"editmenu:{event_id}",
                style="primary"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="👥 Управление участниками",
                callback_data=f"managepeople:{event_id}:0",
                style="primary"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="🗑 Удалить встречу",
                callback_data=f"deleteask:{event_id}",
                style="danger"
            )
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def private_event_keyboard(event: dict, user_id: int | None = None) -> InlineKeyboardMarkup:
    """Клавиатура для личного чата."""
    return event_keyboard(event, user_id)


def group_event_keyboard(event: dict) -> InlineKeyboardMarkup:
    """Клавиатура для группового чата (без персональных кнопок управления)."""
    return event_keyboard(event, None)