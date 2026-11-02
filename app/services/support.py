"""Проверка подписки на поддерживающий чат."""
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.config import settings

async def has_support_membership(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=settings.support_chat_id, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def subscription_prompt() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Вступить в группу", url=settings.support_invite_fallback)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="support:verify")]
    ])