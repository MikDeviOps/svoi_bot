# app/infrastructure/telegram/middlewares.py
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.security_service import SecurityService
from app.infrastructure.db.repositories import (
    SQLAlchemyEventAttendanceRepository,
    SQLAlchemyEventExclusionRepository,
    SQLAlchemyEventMessageRepository,
    SQLAlchemyEventRepository,
    SQLAlchemyParticipantDirectoryRepository,
    SQLAlchemyReviewRepository,
    SQLAlchemySecurityRepository,
    SQLAlchemySignupRepository,
)
from app.infrastructure.redis.client import redis_client
from app.infrastructure.redis.cache import RedisCache

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        bot: Bot,
    ) -> None:
        self._session_maker = session_maker
        self._bot = bot

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._session_maker() as session:
            data["session"] = session
            data["bot"] = self._bot
            cache = RedisCache(redis_client) if redis_client else None
            security_repo = SQLAlchemySecurityRepository(session)
            data["security"] = SecurityService(security_repo, cache, self._bot)
            data["repos"] = {
                "events": SQLAlchemyEventRepository(session),
                "signups": SQLAlchemySignupRepository(session),
                "participants": SQLAlchemyParticipantDirectoryRepository(session),
                "reviews": SQLAlchemyReviewRepository(session),
                "security": security_repo,
                "event_messages": SQLAlchemyEventMessageRepository(session),
                "event_exclusions": SQLAlchemyEventExclusionRepository(session),
                "event_attendance": SQLAlchemyEventAttendanceRepository(session),
            }
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                logger.exception("Update handling failed; transaction rolled back")
                raise