"""Точка входа. Сборка Dispatcher, регистрация middleware и роутеров.

Запуск: ``python -m app.main``.

- Middleware порядок: ``DbSession`` → ``UserUpsert`` → ``Error`` (внешний).
- Роутеры: через ``assemble_root_router()``.
- ``set_my_commands`` — меню бота.
- ``on_shutdown`` — закрытие engine.
"""

from __future__ import annotations

import asyncio
import logging

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import configure_logging, get_settings
from app.db import engine
from app.middlewares import DbSessionMiddleware, ErrorMiddleware, UserUpsertMiddleware
from app.routers import assemble_root_router

logger = structlog.get_logger(__name__)


BOT_COMMANDS = [
    BotCommand(command="start", description="Начать работу с ботом"),
    BotCommand(command="vstrechi", description="Открыть афишу встреч"),
    BotCommand(command="today", description="Показать встречи на сегодня"),
    BotCommand(command="create", description="Создать встречу"),
    BotCommand(command="mine", description="Показать мои встречи"),
    BotCommand(command="cancel", description="Отменить создание встречи"),
    BotCommand(command="help", description="Помощь"),
]


async def on_startup(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    logger.info("bot_started")


async def on_shutdown(bot: Bot) -> None:
    await engine.dispose()
    logger.info("bot_stopped")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Порядок: DbSession (внутренний) → UserUpsert → Error (внешний).
    # В aiogram middleware выполняются снаружи внутрь, поэтому
    # ErrorMiddleware регистрируется первым, чтобы ловить всё.
    dp.update.outer_middleware(ErrorMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware(session_factory))
    dp.update.outer_middleware(UserUpsertMiddleware())

    dp.include_router(assemble_root_router())
    return dp


async def main() -> None:
    configure_logging()
    settings = get_settings()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("polling_start")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    asyncio.run(main())