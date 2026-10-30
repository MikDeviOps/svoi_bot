# app/main.py
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from app.config import settings
from app.infrastructure.db.engine import engine, async_session_maker
from app.infrastructure.redis.client import init_redis, close_redis, redis_client
from app.infrastructure.telegram.middlewares import DatabaseMiddleware
from app.infrastructure.telegram.routers import reputation, reviews, participants, security, start

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(token=settings.BOT_TOKEN)
    redis = await init_redis()
    storage = RedisStorage(redis=redis)
    dp = Dispatcher(storage=storage)
    dp.update.middleware(DatabaseMiddleware(async_session_maker, bot))
    dp.include_router(start.router)
    dp.include_router(reputation.router)
    dp.include_router(reviews.router)
    dp.include_router(participants.router)
    dp.include_router(security.router)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    logger.info("Bot started. Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await dp.storage.close()
        await bot.session.close()
        await close_redis()
        await engine.dispose()
        logger.info("Bot stopped gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested.")