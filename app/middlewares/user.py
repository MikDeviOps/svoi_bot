"""Middleware для проверки банов и обновления каталога участников."""
from collections.abc import Callable, Awaitable
from typing import Any
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.repo.moderation import is_user_blocked
from app.db.repo.directory import upsert_participant
from aiogram.exceptions import TelegramForbiddenError

class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user") or getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        session: AsyncSession = data["session"]
        
        # 1. Проверка на бан
        if await is_user_blocked(session, user.id):
            return  # Молча игнорируем заблокированных (или можно отправить сообщение)

        # 2. Обновление каталога участников (асинхронно, не блокируя основной хендлер)
        display_name = user.full_name or "Участник"
        username = user.username or ""
        await upsert_participant(session, user.id, display_name, username)

        return await handler(event, data)