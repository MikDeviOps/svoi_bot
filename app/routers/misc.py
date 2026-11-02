"""Разные команды: /chatid, /myid, проверка подписки."""
from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from app.filters.owner import IsOwner
from app.services.support import has_support_membership, subscription_prompt

router = Router(name="misc")


@router.message(Command("chatid"), IsOwner())
async def cmd_chatid(message: Message):
    """ID текущего чата (только для владельцев)."""
    chat = message.chat
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.answer("Напиши /chatid в главной группе СВОИ.")
        return
    
    await message.answer(f"🆔 ID группы «{chat.title}»: `{chat.id}`")


@router.message(Command("myid"))
async def cmd_myid(message: Message):
    """Свой Telegram ID."""
    if message.chat.type == ChatType.PRIVATE:
        await message.answer(f"Ваш Telegram ID: {message.from_user.id}")


@router.callback_query(F.data == "support:verify")
async def cb_verify_support(callback: CallbackQuery):
    """Проверка подписки на поддерживающий чат."""
    if await has_support_membership(callback.bot, callback.from_user.id):
        await callback.answer("✅ Подписка подтверждена!", show_alert=True)
        await callback.message.answer("✅ Подписка подтверждена. Теперь можно создавать встречи и записываться на них.")
    else:
        await callback.answer("🔒 Для записи на встречи нажмите «❓ Помощь» в меню бота и вступите в главную группу СВОИ.", show_alert=True)
        await callback.message.answer(
            "🔒 Нажмите «❓ Помощь» в меню бота, затем «👥 Вступить в группу». "
            "После вступления нажмите «✅ Проверить подписку» и вернитесь к встрече.",
            reply_markup=subscription_prompt()
        )