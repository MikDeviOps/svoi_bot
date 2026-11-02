"""Сервис для обработки миграции чатов (basic group -> supergroup)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventMessage
from app.db.repo.groups import upsert_known_group


async def record_chat_migration(
    session: AsyncSession,
    old_chat_id: int,
    new_chat_id: int,
    title: str,
) -> None:
    """Переносит все привязки сообщений и KnownGroup на новый chat_id.

    В Postgres PK составной (event_id, chat_id, message_id), поэтому
    простое UPDATE chat_id может конфликтовать. Обрабатываем построчно.
    """
    # 1. Обновляем KnownGroup
    await upsert_known_group(session, new_chat_id, title)

    # 2. Переносим привязки сообщений
    stmt = select(EventMessage).where(EventMessage.chat_id == old_chat_id)
    result = await session.execute(stmt)
    old_messages = result.scalars().all()

    for msg in old_messages:
        # Проверяем, нет ли уже записи с новым chat_id
        stmt = select(EventMessage).where(
            EventMessage.event_id == msg.event_id,
            EventMessage.chat_id == new_chat_id,
            EventMessage.message_id == msg.message_id,
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Конфликт — удаляем старую запись
            await session.delete(msg)
        else:
            # Обновляем chat_id
            msg.chat_id = new_chat_id