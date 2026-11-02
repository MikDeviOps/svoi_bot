"""Обработка событий чата: добавление бота, миграция ID."""
from aiogram import Router, F
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnownGroup, EventMessage
from app.db.repo.groups import upsert_known_group

router = Router(name="chat_events")

@router.my_chat_member()
async def on_bot_added_to_chat(event: ChatMemberUpdated, session: AsyncSession):
    """Бот добавлен в группу или удалён из неё."""
    if event.new_chat_member.user.id != event.bot.id:
        return  # Не наше событие
    
    chat = event.chat
    if chat.type in ("group", "supergroup"):
        if event.new_chat_member.status in ("member", "administrator", "creator"):
            # Бот добавлен
            await upsert_known_group(session, chat.id, chat.title or "Группа")
        else:
            # Бот удалён (опционально: можно пометить группу как неактивную)
            pass

@router.message(F.migrate_to_chat_id)
async def on_chat_migrated(message: Message, session: AsyncSession):
    """Обработка миграции группы из basic group в supergroup."""
    old_chat_id = message.chat.id
    new_chat_id = message.migrate_to_chat_id
    
    # Обновляем KnownGroup
    await upsert_known_group(session, new_chat_id, message.chat.title or "Группа")
    
    # Обновляем EventMessage: переносим привязку сообщений на новый chat_id
    # Используем UPDATE, так как PK составной (event_id, chat_id, message_id), 
    # и message_id при миграции обычно сохраняется, меняется только chat_id.
    stmt = (
        update(EventMessage)
        .where(EventMessage.chat_id == old_chat_id)
        .values(chat_id=new_chat_id)
    )
    await session.execute(stmt)