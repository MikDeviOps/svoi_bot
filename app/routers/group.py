"""Групповые команды и триггеры."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.routers.create import create_command

router = Router(name="group")


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text.casefold() == "создать встречу")
async def text_create(message: Message, state, session) -> None:
    await create_command(message, session, state)