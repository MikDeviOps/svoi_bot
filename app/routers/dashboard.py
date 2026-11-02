"""Статистика платформы (/stats)."""
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from app.filters.owner import IsOwner
from app.db.repo.stats import get_platform_stats

router = Router(name="dashboard")


@router.message(Command("stats"), IsOwner())
async def cmd_stats(message: Message, session):
    stats = await get_platform_stats(session)
    await message.answer(
        "📊 Статистика платформы СВОИ:\n\n"
        f"📅 Всего встреч: {stats['total_events']}\n"
        f"✍️ Всего записей: {stats['total_signups']}\n"
        f"👥 Всего участников: {stats['total_participants']}"
    )