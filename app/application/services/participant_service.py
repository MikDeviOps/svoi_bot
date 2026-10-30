# app/application/services/participant_service.py
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import User

from app.application.ports.repositories import (
    SignupRepository,
    ParticipantDirectoryRepository,
    EventRepository,
    EventExclusionRepository,
    EventMessageRepository,
)
from app.application.services.security_service import SecurityService
from app.domain.exceptions import (
    EventNotFoundError,
    EventAlreadyStartedError,
    EventFullError,
    AlreadySignedUpError,
    NotSignedUpError,
    EventExcludedError,
    AccessDeniedError,
    UserBlockedError,
)
from app.domain.models import Signup, ParticipantDirectory, EventExclusion, Event
from app.presentation.texts import (
    format_join_success,
    format_cancel_success,
    event_origin_label,
)

logger = logging.getLogger(__name__)


class JoinResult:
    def __init__(self, message: str, available: int, event: Event, notify_source: bool) -> None:
        self.message = message
        self.available = available
        self.event = event
        self.notify_source = notify_source


class ParticipantService:
    def __init__(
        self,
        signups: SignupRepository,
        participants: ParticipantDirectoryRepository,
        events: EventRepository,
        exclusions: EventExclusionRepository,
        event_messages: EventMessageRepository,
        security: SecurityService,
        bot: Bot,
    ) -> None:
        self._signups = signups
        self._participants = participants
        self._events = events
        self._exclusions = exclusions
        self._event_messages = event_messages
        self._security = security
        self._bot = bot

    async def join_event(
        self,
        event_id: int,
        user: User,
        *,
        current_chat_type: str | None,
        current_chat_id: int | None,
    ) -> JoinResult:
        await self._security.check_user_blocked(user.id, user.username)
        if not await self._security.check_support_membership(user.id):
            from app.domain.exceptions import DomainError
            raise DomainError(
                "🔒 Для записи на встречи необходимо вступить в главную группу СВОИ.\n\n"
                "❓ Нажмите «Помощь» в меню бота, затем «👥 Вступить в группу».\n\n"
                "После вступления нажмите «✅ Проверить подписку» и вернитесь к встрече."
            )
        result = await self._events.get_with_booked_count(event_id)
        if result is None:
            raise EventNotFoundError()
        event, booked = result
        if not await self._security.check_event_access(
            event, user.id, current_chat_type, current_chat_id
        ):
            raise AccessDeniedError()
        try:
            event_dt = datetime.fromisoformat(f"{event.date}T{event.time}").replace(tzinfo=timezone.utc)
            if event_dt <= datetime.now(timezone.utc):
                raise EventAlreadyStartedError()
        except ValueError:
            pass
        if await self._exclusions.is_excluded(event_id, user.id):
            raise EventExcludedError()
        if await self._signups.get(event_id, user.id) is not None:
            available = max(0, event.capacity - booked)
            raise AlreadySignedUpError(available)
        if booked >= event.capacity:
            raise EventFullError()
        telegram_name = (
            f"@{user.username}" if user.username else (user.full_name or "Имя не указано")
        )[:129]
        signup = Signup(
            event_id=event_id,
            user_id=user.id,
            telegram_name=telegram_name,
        )
        await self._signups.create(signup)
        participant = ParticipantDirectory(
            user_id=user.id,
            display_name=(user.full_name or "Участник")[:129],
            last_signup_at=datetime.now(timezone.utc),
            username=(user.username or "")[:32],
        )
        await self._participants.upsert(participant)
        available = max(0, event.capacity - (booked + 1))
        message = (
            f"Вы записаны на встречу «{event.title}»!\n"
            f"{event.date} в {event.time}\n"
            f"Адрес: {event.address}\n"
            f"Условия: {event.conditions}\n"
            f"Свободно мест: {available}.\n\n"
            "⚠️ Бот не проверяет оплату. Если указан депозит, свяжитесь с организатором самостоятельно."
        )
        return JoinResult(
            message=message,
            available=available,
            event=event,
            notify_source=True,
        )

    async def cancel_signup(
        self,
        event_id: int,
        user: User,
    ) -> JoinResult:
        result = await self._events.get_with_booked_count(event_id)
        if result is None:
            raise EventNotFoundError()
        event, booked = result
        if await self._signups.delete(event_id, user.id) is False:
            raise NotSignedUpError()
        available = max(0, event.capacity - (booked - 1))
        message = f"Запись на встречу «{event.title}» отменена. Свободно мест: {available}."
        return JoinResult(
            message=message,
            available=available,
            event=event,
            notify_source=True,
        )

    async def exclude_user(self, event_id: int, user_id: int, excluded_by: int) -> None:
        exclusion = EventExclusion(
            event_id=event_id, user_id=user_id, excluded_by=excluded_by
        )
        await self._exclusions.add(exclusion)
        await self._signups.delete(event_id, user_id)

    async def restore_user(self, event_id: int, user_id: int) -> None:
        await self._exclusions.remove(event_id, user_id)

    async def notify_source_group(
        self, event: Event, user: User, available: int, *, joined: bool
    ) -> None:
        if event.source_chat_id is None:
            return
        mention = f'<a href="tg://user?id={user.id}">{user.full_name or str(user.id)}</a>'
        action = "записался(ась)" if joined else "отменил(а) запись"
        icon = "✅" if joined else "❌"
        text = (
            f"{icon} {mention} {action} на встречу «{event.title}».\n"
            f"👥 Свободно мест: {available}."
        )
        try:
            await self._bot.send_message(
                chat_id=event.source_chat_id, text=text, parse_mode="HTML"
            )
        except TelegramAPIError as exc:
            logger.warning("Could not notify source group for event %s: %s", event.id, exc)