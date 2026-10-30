# app/infrastructure/redis/client.py
from __future__ import annotations

import redis.asyncio as redis

from app.config import settings

# Глобальный клиент, инициализируется в main.py
redis_client: redis.Redis | None = None


async def init_redis() -> redis.Redis:
    global redis_client
    redis_client = redis.from_url(
        settings.redis_cache_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=5.0,
        retry_on_timeout=True,
    )
    await redis_client.ping()
    return redis_client


async def close_redis() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None