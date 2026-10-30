# app/infrastructure/redis/cache.py
from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisCache:
    """Реализация CachePort поверх redis.asyncio.

    Деградация: если Redis недоступен, операции возвращают None / no-op
    и пишут warning в лог. Бизнес-логика не падает.
    """

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    async def get(self, key: str) -> Optional[str]:
        try:
            return await self._client.get(key)
        except redis.RedisError as exc:
            logger.warning("Redis GET failed for %s: %s", key, exc)
            return None

    async def set(self, key: str, value: str, *, ttl: int) -> None:
        try:
            await self._client.set(key, value, ex=ttl)
        except redis.RedisError as exc:
            logger.warning("Redis SET failed for %s: %s", key, exc)

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except redis.RedisError as exc:
            logger.warning("Redis DELETE failed for %s: %s", key, exc)

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self._client.exists(key))
        except redis.RedisError as exc:
            logger.warning("Redis EXISTS failed for %s: %s", key, exc)
            return False