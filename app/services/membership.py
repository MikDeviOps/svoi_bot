"""Проверки членства в чатах."""
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

async def resolve_group_id(bot: Bot, chat_id: int | str) -> int:
    if isinstance(chat_id, str) and not str(chat_id).startswith("-"):
        chat = await bot.get_chat(chat_id)
        return chat.id
    return int(chat_id)

async def is_source_chat_member(bot: Bot, chat_id: int | str, user_id: int) -> bool:
    try:
        resolved_id = await resolve_group_id(bot, chat_id)
        member = await bot.get_chat_member(chat_id=resolved_id, user_id=user_id)
        return member.status in ("member", "administrator", "creator", "restricted")
    except TelegramAPIError:
        return False