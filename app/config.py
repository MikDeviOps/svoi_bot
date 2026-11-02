"""Конфигурация СВОИ: переменные окружения через pydantic-settings."""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(..., alias="BOT_TOKEN")

    postgres_user: str = Field("svoi", alias="POSTGRES_USER")
    postgres_password: str = Field("svoi", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("svoi", alias="POSTGRES_DB")
    postgres_host: str = Field("postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")

    redis_password: str = Field("", alias="REDIS_PASSWORD")
    redis_host: str = Field("redis", alias="REDIS_HOST")
    redis_port: int = Field(6379, alias="REDIS_PORT")
    redis_db: int = Field(0, alias="REDIS_DB")

    owners: tuple[int, ...] = Field((), alias="OWNERS")
    registration_owner: int = Field(0, alias="REGISTRATION_OWNER")
    support_chat_id: int = Field(0, alias="SUPPORT_CHAT_ID")
    support_invite_fallback: str = Field(
        "https://t.me/+nucXNSA9t5QzZmEy", alias="SUPPORT_INVITE_FALLBACK"
    )
    min_group_size: int = Field(20, alias="MIN_GROUP_SIZE")
    daily_event_limit: int = Field(3, alias="DAILY_EVENT_LIMIT")

    tz: str = Field("Europe/Moscow", alias="TZ_NAME")
    data_dir: Path = Field(Path("/data"), alias="DATA_DIR")

    @field_validator("owners", mode="before")
    @classmethod
    def _split_owners(cls, v):
        if isinstance(v, str):
            return tuple(int(x) for x in v.split(",") if x.strip())
        return v

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.tz)


settings = Settings()