"""Текстовые триггеры для кнопок клавиатуры."""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from app.routers.start import show_welcome, cmd_start
from app.routers.agenda import cmd_agenda
from app.routers.creation import cmd_create_start
from app.routers.admin import cmd_help

router = Router(name="text_triggers")

# Перехват кнопок главного меню
@router.message(F.text == "🏠 Меню")
async def trigger_menu(message: Message):
    await show_welcome(message)

@router.message(F.text == "📅 Афиша встреч")
async def trigger_agenda(message: Message):
    # Имитируем вызов команды, передавая те же аргументы
    await cmd_agenda(message, message.bot_data.get("session")) 
    # Примечание: session берётся из middleware автоматически, 
    # поэтому просто вызываем хендлер, он получит session из data

@router.message(F.text == "➕ Создать встречу")
async def trigger_create(message: Message):
    await cmd_create_start(message, message.bot_data.get("fsm_context"))

@router.message(F.text == "❓ Помощь")
async def trigger_help(message: Message):
    await cmd_help(message)

@router.message(F.text == "📋 Мои встречи")
async def trigger_mine(message: Message):
    # Импортируем здесь, чтобы избежать циклических зависимостей, или выносим в общий сервис
    from app.routers.admin import cmd_mine
    await cmd_mine(message, message.bot_data.get("session"))