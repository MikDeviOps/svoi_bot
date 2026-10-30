# app/infrastructure/telegram/routers/start.py
from __future__ import annotations

from aiogram import Router, Bot, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.application.services.participant_service import ParticipantService
from app.application.services.security_service import SecurityService
from app.application.services.event_message_service import EventMessageService
from app.application.services.event_service import EventService
from app.domain.exceptions import DomainError
from app.infrastructure.telegram.keyboards import event_keyboard, subscription_keyboard
from app.presentation.texts import event_card_text

router = Router(name="start")


@router.message(CommandStart())
async def start_command(message: Message, repos: dict, security: SecurityService, bot: Bot) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("join_"):
        event_id = int(args[1].split("_")[1])
        service = ParticipantService(
            repos["signups"], repos["participants"], repos["events"],
            repos["event_exclusions"], repos["event_messages"], security, bot,
        )
        try:
            result = await service.join_event(
                event_id, message.from_user,
                current_chat_type=message.chat.type,
                current_chat_id=message.chat.id,
            )
            await message.answer(result.message)
            await EventMessageService(repos["event_messages"], repos["events"], bot).refresh_event_messages(event_id)
            await service.notify_source_group(result.event, message.from_user, result.available, joined=True)
        except DomainError as exc:
            await message.answer(exc.message)
        return
    await message.answer(
        "Привет! Я бот платформы СВОИ.\n\n"
        "Используй /rating для статистики, /organizer для списка организаторов.",
    )