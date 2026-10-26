"""Middleware для aiogram.

- ``DbSessionMiddleware`` — одна async-сессия на update (commit/rollback/close).
- ``UserUpsertMiddleware`` — атомарный upsert ``users`` через
  ``INSERT ... ON CONFLICT`` (без race condition).
- ``ErrorMiddleware`` — ``DomainError`` → user-safe текст; неожиданные —
  лог + общее сообщение.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import User
from app.errors import DomainError

logger = structlog.get_logger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Одна сессия на update. Commit/rollback автоматически.

    Сессия кладётся в ``data["session"]``. ``commit`` — если хендлер
    отработал без исключения; ``rollback`` — если ``DomainError`` или
    любое другое; ``close`` — в ``finally``.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except DomainError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise


class UserUpsertMiddleware(BaseMiddleware):
    """Upsert ``users`` по ``tg_id`` при каждом update от пользователя.

    Использует ``INSERT ... ON CONFLICT (tg_id) DO UPDATE`` — **атомарно**.
    Два параллельных update от одного ``tg_id`` не падают в
    ``UniqueViolationError`` (race condition, который был при
    ``session.get`` + ``session.add``).

    Кладёт ORM-объект ``User`` в ``data["user"]``.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")

        if tg_user is not None and session is not None:
            stmt = (
                pg_insert(User)
                .values(
                    tg_id=tg_user.id,
                    username=tg_user.username or "",
                    full_name=tg_user.full_name or "",
                )
                .on_conflict_do_update(
                    index_elements=[User.tg_id],
                    set_={
                        "username": tg_user.username or "",
                        "full_name": tg_user.full_name or "",
                    },
                )
            )
            await session.execute(stmt)
            await session.flush()

            user = await session.get(User, tg_user.id)
            data["user"] = user

        return await handler(event, data)


class ErrorMiddleware(BaseMiddleware):
    """Ловит ``DomainError`` → ``answer(user_message)``.

    Неожиданные исключения — логирует и шлёт общее сообщение.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except DomainError as exc:
            logger.info(
                "domain_error",
                error=type(exc).__name__,
                message=exc.user_message,
            )
            await self._reply(event, exc.user_message)
            return None
        except Exception as exc:
            logger.exception(
                "unhandled_error",
                error=type(exc).__name__,
                exc_info=exc,
            )
            await self._reply(event, "Что-то пошло не так. Попробуйте позже.")
            return None

    @staticmethod
    async def _reply(event: TelegramObject, text: str) -> None:
        if isinstance(event, Update):
            target = event.message or (
                event.callback_query.message if event.callback_query else None
            )
        elif isinstance(event, Message):
            target = event
        elif isinstance(event, CallbackQuery):
            target = event.message
        else:
            target = None
        if target is not None:
            await target.answer(text)