"""Точка входа бота СВОИ (aiogram 3.x)."""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, BotCommandScopeChat

from app.config import settings
from app.db.engine import dispose_engine
from app.middlewares.db import DbSessionMiddleware
from app.middlewares.user import UserMiddleware
from app.services.events import cleanup_finished_event_cards

# Роутеры
from app.routers import (
    start, agenda, creation, participants, management, admin,
    groups_reg, chat_events, text_triggers,
    reputation, dashboard, directory, moderation, reviews, misc,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    """Настройка команд бота при запуске."""
    logger.info("Bot started. Setting up commands...")

    private_commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="vstrechi", description="Афиша встреч"),
        BotCommand(command="create", description="Создать встречу"),
        BotCommand(command="mine", description="Мои встречи"),
        BotCommand(command="organizer", description="История организаторов"),
        BotCommand(command="rating", description="Моя активность"),
        BotCommand(command="review", description="Оставить отзыв"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())

    group_commands = [
        BotCommand(command="vstrechi", description="Встречи и регистрация группы"),
        BotCommand(command="create", description="Создать встречу"),
        BotCommand(command="grouprating", description="Активность чата"),
    ]
    await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())

    # Команды для каждого владельца
    owner_commands = private_commands + [
        BotCommand(command="admin", description="Панель владельца"),
        BotCommand(command="base", description="База участников"),
        BotCommand(command="stats", description="Статистика платформы"),
        BotCommand(command="blocks", description="Блокировки"),
        BotCommand(command="groups", description="Заявки и доступ групп"),
        BotCommand(command="chatid", description="ID этого чата"),
    ]
    for owner_id in settings.owners:
        try:
            await bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=owner_id))
        except Exception:
            logger.exception("Не удалось настроить личное меню владельца %s", owner_id)

    logger.info("Bot commands configured successfully.")


async def on_shutdown(bot: Bot):
    """Очистка ресурсов при остановке."""
    logger.info("Bot shutting down...")
    await dispose_engine()


async def periodic_cleanup(bot: Bot):
    """Фоновая задача: очистка карточек завершившихся встреч каждые 10 минут."""
    await asyncio.sleep(15)
    while True:
        try:
            await cleanup_finished_event_cards(bot)
        except Exception:
            logger.exception("Ошибка автоматической очистки встреч")
        await asyncio.sleep(600)


async def handle_error(update, exception):
    """Обработчик ошибок Telegram."""
    logger.error("Ошибка обработчика Telegram: %s", exception, exc_info=exception)
    return True


async def main():
    logger.info("Initializing bot...")

    storage = RedisStorage.from_url(settings.redis_url)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    # Middleware
    dp.update.middleware(DbSessionMiddleware())
    dp.update.middleware(UserMiddleware())

    # Роутеры
    dp.include_router(start.router)
    dp.include_router(text_triggers.router)
    dp.include_router(agenda.router)
    dp.include_router(creation.router)
    dp.include_router(participants.router)
    dp.include_router(management.router)

    # Специализированные роутеры
    dp.include_router(reputation.router)
    dp.include_router(dashboard.router)
    dp.include_router(directory.router)
    dp.include_router(moderation.router)
    dp.include_router(reviews.router)
    dp.include_router(misc.router)

    # Администрирование и группы
    dp.include_router(admin.router)
    dp.include_router(groups_reg.router)

    # События чата
    dp.include_router(chat_events.router)

    # Хуки
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Обработчик ошибок
    dp.errors.register(handle_error)

    # Запуск
    logger.info("Starting polling...")
    cleanup_task = None
    try:
        cleanup_task = asyncio.create_task(periodic_cleanup(bot))
        await dp.start_polling(bot, drop_pending_updates=True)
    except asyncio.CancelledError:
        logger.info("Polling was cancelled.")
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user!")
    finally:
        if cleanup_task:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot startup interrupted.")