"""Админ-панель владельца: /stats (только owner_id)."""

from __future__ import annotations

from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import Event, Signup, User

router = Router(name="admin")


def _is_owner(user_id: int) -> bool:
    return user_id == get_settings().owner_id


@router.message(Command("stats"))
async def stats(message: Message, session: AsyncSession) -> None:
    if not _is_owner(message.from_user.id):
        await message.answer("⛔ Команда доступна только владельцу бота.")
        return

    settings = get_settings()
    now = datetime.now(settings.timezone)

    users_total = await session.scalar(select(func.count()).select_from(User)) or 0
    events_total = await session.scalar(select(func.count()).select_from(Event)) or 0
    signups_total = await session.scalar(select(func.count()).select_from(Signup)) or 0
    upcoming = await session.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.starts_at > now, Event.deleted_at.is_(None))
    ) or 0

    await message.answer(
        "📊 <b>СВОИ — состояние</b>\n\n"
        f"👥 Пользователей: <b>{users_total}</b>\n"
        f"📅 Встреч всего: <b>{events_total}</b>\n"
        f"🟢 Предстоящих: <b>{upcoming}</b>\n"
        f"🙋 Записей: <b>{signups_total}</b>",
        parse_mode="HTML",
    )