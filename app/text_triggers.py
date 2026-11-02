"""Текстовые триггеры для кнопок ReplyKeyboard."""
from aiogram import Router, F
from aiogram.types import Message

from app.routers.start import show_welcome

router = Router(name="text_triggers")


@router.message(F.text == "🏠 Меню")
async def trigger_menu(message: Message):
    await show_welcome(message)


# Остальные кнопки (📅 Афиша встреч, ➕ Создать встречу, ❓ Помощь, 📋 Мои встречи)
# работают через Command(...) в своих роутерах. ReplyKeyboard просто отправляет текст,
# и aiogram сам найдёт нужный хендлер по F.text или Command.