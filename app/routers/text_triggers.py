"""Текстовые триггеры для кнопок ReplyKeyboard."""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.routers.start import show_welcome
from app.routers.agenda import cmd_agenda
from app.routers.creation import cmd_create_start
from app.routers.admin import cmd_help, cmd_mine

router = Router(name="text_triggers")


@router.message(F.text == "🏠 Меню")
async def trigger_menu(message: Message):
    await show_welcome(message)


@router.message(F.text == "📅 Афиша встреч")
async def trigger_agenda(message: Message, session: AsyncSession):
    await cmd_agenda(message, session)


@router.message(F.text == "➕ Создать встречу")
async def trigger_create(message: Message, state: FSMContext):
    await cmd_create_start(message, state)


@router.message(F.text == "❓ Помощь")
async def trigger_help(message: Message):
    await cmd_help(message)


@router.message(F.text == "📋 Мои встречи")
async def trigger_mine(message: Message, session: AsyncSession):
    await cmd_mine(message, session)
