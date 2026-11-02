"""Репозиторий для работы с группами и заявками."""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import GroupApplication, KnownGroup

async def upsert_known_group(session: AsyncSession, chat_id: int, title: str) -> None:
    stmt = select(KnownGroup).where(KnownGroup.chat_id == chat_id)
    result = await session.execute(stmt)
    group = result.scalar_one_or_none()
    
    if group:
        if group.title != title:
            group.title = title
    else:
        session.add(KnownGroup(chat_id=chat_id, title=title))

async def get_pending_applications(session: AsyncSession) -> list[GroupApplication]:
    stmt = select(GroupApplication).where(GroupApplication.status == "pending").order_by(GroupApplication.requested_at.desc())
    result = await session.execute(stmt)
    return result.scalars().all()

async def update_application_status(session: AsyncSession, chat_id: int, status: str, reviewer_id: int) -> bool:
    stmt = (
        update(GroupApplication)
        .where(GroupApplication.chat_id == chat_id, GroupApplication.status == "pending")
        .values(status=status, reviewed_by=reviewer_id)
    )
    result = await session.execute(stmt)
    return result.rowcount > 0