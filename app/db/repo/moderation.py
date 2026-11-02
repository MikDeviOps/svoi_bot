"""Репозиторий для проверок модерации."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import BlockedUser, BlockedGroup

async def is_user_blocked(session: AsyncSession, user_id: int) -> bool:
    stmt = select(BlockedUser.user_id).where(BlockedUser.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None

async def is_group_blocked(session: AsyncSession, chat_id: int) -> bool:
    stmt = select(BlockedGroup.chat_id).where(BlockedGroup.chat_id == chat_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None