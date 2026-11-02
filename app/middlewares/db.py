"""Middleware для инъекции сессии SQLAlchemy в каждый update."""
from collections.abc import Callable, Awaitable
from typing import Any
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from app.db.engine import session_scope

class DbSessionMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with session_scope() as session:
            data["session"] = session
            return await handler(event, data)