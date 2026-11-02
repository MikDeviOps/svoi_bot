"""Общие клавиатуры и константы."""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup

PRIVATE_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Афиша встреч"), KeyboardButton(text="➕ Создать встречу")],
        [KeyboardButton(text="📋 Мои встречи"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="🏠 Меню")]
    ],
    resize_keyboard=True,
    is_persistent=True
)

CATEGORIES = {
    "sport": "🏃 Спорт",
    "culture": "🎨 Культура",
    "education": "📚 Образование",
    "business": "💼 Бизнес",
    "entertainment": "🎉 Развлечения",
    "other": "🔹 Другое"
}

EDIT_FIELDS = {
    "title": "Название",
    "description": "Описание",
    "date": "Дата (ДД.ММ.ГГГГ)",
    "time": "Время (ЧЧ:ММ)",
    "address": "Адрес",
    "conditions": "Условия",
    "capacity": "Вместимость (число)",
    "category": "Категория"
}

DAYS_OF_WEEK = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]