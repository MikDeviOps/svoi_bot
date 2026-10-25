"""Fallback: /help и неизвестные команды/сообщения.

Здесь же — текстовые триггеры «помощь», «❓ Помощь».
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="fallback")


HELP_TEXT = (
    "Я помогаю найти и создать встречи в Москве.\n\n"
    "/vstrechi — открыть афишу\n"
    "/today — встречи на сегодня\n"
    "/create — создать встречу\n"
    "/mine — мои встречи\n"
    "/help — эта справка\n\n"
    "В группе также можно написать отдельным сообщением: «встречи», "
    "«ближайшие встречи», «создать встречу» или «помощь»."
)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(F.text.casefold().in_({"помощь", "❓ помощь"}))
async def help_text(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message()
async def unknown(message: Message) -> None:
    """Неизвестные команды/текст — в группах молчим, в личке — меню."""
    if message.chat.type == "private":
        await message.answer("Не понимаю. /help — список команд.")