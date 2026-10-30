"""Слой доступа к базе данных.

Содержит:
- ``Base`` — декларативная база SQLAlchemy 2.x.
- Миксины ``TimestampMixin`` и ``SoftDeleteMixin``.
- ORM-модели: ``User``, ``KnownGroup``, ``Event``, ``Signup``, ``EventMessage``.
- ``engine``, ``async_sessionmaker`` и фабрику ``get_session()``.

Модуль НЕ содержит бизнес-логики и не знает про Telegram/aiogram.
Все запросы — через ``select()``/``insert()``/``update()`` в сервисах
(см. ``app/services/*.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings


# Единая конвенция имён для constraint'ов и индексов — важно для Alembic,
# чтобы autogenerate не плодил дубли при переименованиях.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Декларативная база с единой конвенцией имён."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Добавляет ``created_at``/``updated_at`` с автообновлением."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Добавляет ``deleted_at`` — физически записи не удаляем."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


# ---------------------------------------------------------------------------
# ORM-модели
# ---------------------------------------------------------------------------


class User(Base, TimestampMixin):
    """Пользователь Telegram. Справочник вместо денормализации в ``events``."""

    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    events_owned: Mapped[list["Event"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class KnownGroup(Base, TimestampMixin):
    """Групповой чат, в котором бот зарегистрирован через /create."""

    __tablename__ = "known_groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Event(Base, TimestampMixin, SoftDeleteMixin):
    """Встреча. ``starts_at`` — timestamptz вместо пары ``date``+``time``."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    address: Mapped[str] = mapped_column(String(250), nullable=False)
    conditions: Mapped[str] = mapped_column(String(500), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    source_chat_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("known_groups.chat_id", ondelete="SET NULL"), nullable=True
    )
    source_chat_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    photo_file_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    owner: Mapped[User] = relationship(back_populates="events_owned")
    signups: Mapped[list["Signup"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    messages: Mapped[list["EventMessage"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("capacity BETWEEN 1 AND 1000", name="capacity_range"),
        CheckConstraint(
            "visibility IN ('public','chat')", name="visibility_values"
        ),
        CheckConstraint("char_length(title) BETWEEN 3 AND 100", name="title_len"),
        CheckConstraint("char_length(address) BETWEEN 5 AND 250", name="address_len"),
        CheckConstraint(
            "char_length(conditions) BETWEEN 2 AND 500", name="conditions_len"
        ),
        Index(
            "ix_events_agenda",
            "visibility",
            "source_chat_id",
            "starts_at",
            "category",
        ),
        Index("ix_events_owner", "owner_id", "starts_at"),
    )


class Signup(Base):
    """Запись пользователя на встречу. PK (event_id, user_id) — от дублей."""

    __tablename__ = "signups"

    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), primary_key=True
    )
    telegram_name: Mapped[str] = mapped_column(String(129), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    event: Mapped[Event] = relationship(back_populates="signups")


class EventMessage(Base):
    """Карточка события, отправленная в чат. Нужна для refresh счётчика мест."""

    __tablename__ = "event_messages"

    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    event: Mapped[Event] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# Engine / session
# ---------------------------------------------------------------------------

_settings = get_settings()
engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Фабрика сессий для middleware. Commit/rollback — на стороне middleware."""
    async with async_session_factory() as session:
        yield session