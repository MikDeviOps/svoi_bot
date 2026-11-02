"""ORM-модели СВОИ (PostgreSQL)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Integer, SmallInteger, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, utcnow


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    owner_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_username: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(Text, nullable=False, default="other")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    source_chat_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="public")
    photo_file_id: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        CheckConstraint("capacity > 0", name="capacity_positive"),
        CheckConstraint("visibility IN ('chat','public')", name="visibility_allowed"),
        Index("ix_events_agenda", "visibility", "source_chat_id", "starts_at", "category"),
    )

    signups: Mapped[list["Signup"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    messages: Mapped[list["EventMessage"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class Signup(TimestampMixin):
    __tablename__ = "signups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_name: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_signups_event_user"),
        Index("ix_signups_user", "user_id"),
    )
    event: Mapped[Event] = relationship(back_populates="signups")


class ParticipantDirectory(Base):
    __tablename__ = "participant_directory"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(CITEXT, nullable=False, default="")
    last_signup_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GroupApplication(Base):
    __tablename__ = "group_applications"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    applicant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applicant_name: Mapped[str] = mapped_column(Text, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (CheckConstraint("status IN ('pending','approved','rejected','revoked')", name="status_allowed"),)


class GroupApprovalLog(Base):
    __tablename__ = "group_approval_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnownGroup(Base):
    __tablename__ = "known_groups"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)


class EventMessage(Base):
    __tablename__ = "event_messages"
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event: Mapped[Event] = relationship(back_populates="messages")


class AgendaCooldown(Base):
    __tablename__ = "agenda_cooldowns"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_used: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    warning_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class BlockedUser(Base):
    __tablename__ = "blocked_users"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PendingUsernameBan(Base):
    __tablename__ = "pending_username_bans"
    username: Mapped[str] = mapped_column(CITEXT, primary_key=True)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resolved_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)


class BlockedGroup(Base):
    __tablename__ = "blocked_groups"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EventExclusion(Base):
    __tablename__ = "event_exclusions"
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    excluded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    excluded_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EventAttendance(Base):
    __tablename__ = "event_attendance"
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attended: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confirmed_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventReview(Base):
    __tablename__ = "event_reviews"
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stars: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    review: Mapped[str] = mapped_column(Text, nullable=False, default="")
    event_title: Mapped[str] = mapped_column(Text, nullable=False)
    organizer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("stars BETWEEN 1 AND 5", name="stars_range"),)


class OrganizerStatReset(Base):
    __tablename__ = "organizer_stat_resets"
    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_cutoff: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    signup_cutoff: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)