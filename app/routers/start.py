"""Роутер для команд /start, глубоких ссылок и главного меню."""
import re
from aiogram import Router, F, Bot
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards.common import PRIVATE_MENU
from app.services.events import get_event_with_count, event_card_text
from app.keyboards.events import private_event_keyboard

router = Router(name="start")

@router.message(CommandStart(deep_link=True))
async def handle_deep_link(message: Message, session: AsyncSession):
    """Обработка глубоких ссылок вида /start event_123"""
    # message.text будет вида "/start event_123" или "event_123" в зависимости от клиента
    # В aiogram 3 при deep_link=True, message.text содержит только аргумент (или /start arg)
    text = message.text or ""
    match = re.search(r"event_(\d+)", text)
    
    if not match:
        await show_welcome(message)
        return

    event_id = int(match.group(1))
    event = await get_event_with_count(session, event_id)
    
    if not event:
        await message.answer("⚠️ Встреча не найдена или была удалена.")
        return

    # Проверка видимости (упрощённая для личного чата)
    if event["visibility"] == "chat":
        await message.answer(
            "⚠️ Эта встреча доступна только участникам чата-организатора.\n"
            "Чтобы присоединиться, используйте кнопку в исходном чате."
        )
        return

    text_card = event_card_text(event, private_details=True)
    if event["photo_file_id"]:
        await message.answer_photo(
            photo=event["photo_file_id"],
            caption=text_card,
            reply_markup=private_event_keyboard(event, message.from_user.id)
        )
    else:
        await message.answer(
            text_card,
            reply_markup=private_event_keyboard(event, message.from_user.id)
        )

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обычный старт без глубокой ссылки."""
    await show_welcome(message)

@router.message(F.text == "🏠 Меню")
async def cmd_menu(message: Message):
    """Восстановление кнопок меню."""
    await show_welcome(message)

async def show_welcome(message: Message):
    """Показывает приветствие и постоянную клавиатуру."""
    await message.answer(
        "👋 Добро пожаловать в бота **СВОИ**!\n\n"
        "Здесь вы можете найти интересные встречи в Москве, создать свою или управлять уже существующими.\n\n"
        "Используйте кнопки ниже для навигации:",
        reply_markup=PRIVATE_MENU
    )