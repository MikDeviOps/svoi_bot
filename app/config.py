# app/config.py
from __future__ import annotations

from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bot
    BOT_TOKEN: str = Field(..., description="Telegram Bot Token")

    # PostgreSQL
    POSTGRES_USER: str = "svoi_user"
    POSTGRES_PASSWORD: str = "svoi_password"
    POSTGRES_DB: str = "svoi_db"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url(self) -> str:
        # Для Alembic миграций (psycopg2)
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = Field(..., description="Redis password")
    REDIS_FSM_DB: int = 0
    REDIS_CACHE_DB: int = 1

    @property
    def redis_fsm_url(self) -> str:
        return (
            f"redis://:{self.REDIS_PASSWORD}"
            f"@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_FSM_DB}"
        )

    @property
    def redis_cache_url(self) -> str:
        return (
            f"redis://:{self.REDIS_PASSWORD}"
            f"@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_CACHE_DB}"
        )

    # Business Logic
    SUPPORT_CHAT_ID: int = Field(..., description="Numeric ID of the support chat")
    OWNERS: List[int] = Field(
        default=[490290960, 788430312],
        description="Comma-separated list of owner IDs",
    )
    MIN_GROUP_SIZE: int = 20

    @field_validator("OWNERS", mode="before")
    @classmethod
    def parse_owners(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip().isdigit()]
        if isinstance(v, list):
            return [int(x) for x in v]
        return v

    # Legacy SQLite path for migration
    LEGACY_SQLITE_PATH: str = "svoi.db"


settings = Settings()