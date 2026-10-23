"""Конфигурация приложения. Минимальная версия для Шага 1.

Полная версия (structlog, лимиты, TZ-aware now()) — Шаг 2.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    database_url: str = "postgresql+asyncpg://svoi:svoi@localhost:5432/svoi"
    owner_id: int = 0
    tz: str = "Europe/Moscow"


@lru_cache
def get_settings() -> Settings:
    return Settings()