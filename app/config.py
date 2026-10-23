"""Конфигурация приложения.

Единственный источник ENV. Отсюда берутся:
- ``settings`` — pydantic-settings (BOT_TOKEN, DATABASE_URL, лимиты, TZ);
- ``configure_logging()`` — structlog JSON;
- ``now()`` — TZ-aware текущее время (единственное место в проекте).

"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из ENV/`.env`. Все поля с дефолтами — приложение стартует без секретов."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    bot_token: str = ""
    owner_id: int = 0

    # --- База данных ---
    database_url: str = (
        "postgresql+asyncpg://svoi:svoi@localhost:5432/svoi"
    )
    database_url_test: str = ""  # для тестов; если пусто — используется database_url

    # --- Время ---
    tz: str = "Europe/Moscow"

    # --- Лимиты предметной области (синхронизированы с CHECK в БД) ---
    title_min_len: int = 3
    title_max_len: int = 100
    description_max_len: int = 1000
    address_min_len: int = 5
    address_max_len: int = 250
    conditions_min_len: int = 2
    conditions_max_len: int = 500
    capacity_min: int = 1
    capacity_max: int = 1000
    event_horizon_days: int = 365

    # --- Логирование ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True  # False — человекочитаемо (dev), True — JSON (prod)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.tz)

    @property
    def test_database_url(self) -> str:
        """URL для тестов: ``DATABASE_URL_TEST`` или ``DATABASE_URL`` с суффиксом ``_test``."""
        if self.database_url_test:
            return self.database_url_test
        # postgresql+asyncpg://user:pass@host:port/db → .../db_test
        base, _, _db = self.database_url.rpartition("/")
        return f"{base}/svoi_test"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging() -> None:
    """structlog: JSON в prod, красивый вывод в dev. Уровень — из Settings."""
    settings = get_settings()
    level = getattr(logging, settings.log_level)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=False)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        timestamper,
    ]

    if settings.log_json:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
        force=True,
    )


def now() -> datetime:
    """Единственное место, где берётся «сейчас». TZ-aware, Europe/Moscow по умолчанию."""
    return datetime.now(get_settings().timezone)