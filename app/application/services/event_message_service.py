# app/application/services/event_message_service.py
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from app.application.ports.repositories import EventMessageRepository, EventRepository
from app.domain.models import EventMessage
from app.infrastructure.telegram.keyboards import event_keyboard
from app.presentation.texts import event_card_text

logger = logging.getLogger(__name__)


class EventMessageService:
    def __init__(
        self,
        event_messages: EventMessageRepository,
        events: EventRepository,
        bot: Bot,
    ) -> None:
        self._event_messages = event_messages
        self._events = events
        self._bot = bot

    async def register_message(
        self, event_id: int, chat_id: int, message_id: int
    ) -> None:
        msg = EventMessage(
            event_id=event_id, chat_id=chat_id, message_id=message_id
        )
        await self._event_messages.save(msg)

    async def refresh_event_messages(self, event_id: int) -> None:
        result = await self._events.get_with_booked_count(event_id)
        if result is None:
            return
        event, booked = result
        messages = await self._event_messages.list_by_event(event_id)
        text = event_card_text(event, booked, private_details=False)
        keyboard = event_keyboard(event, booked, viewer_id=None)
        for msg in messages:
            try:
                await self._bot.edit_message_text(
                    text=text,
                    chat_id=msg.chat_id,
                    message_id=msg.message_id,
                    reply_markup=keyboard,
                )
            except TelegramBadRequest:
                pass