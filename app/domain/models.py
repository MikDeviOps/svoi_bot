# app/domain/models.py
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    time: Mapped[str] = mapped_column(String(5), nullable=False)   # HH:MM
    address: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[str] = mapped_column(Text, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    category: Mapped[str] = mapped_column(String(50), default="other")
    source_chat_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    description: Mapped[str] = mapped_column(Text, default="")
    owner_name: Mapped[str] = mapped_column(String(255), default="")
    source_chat_title: Mapped[str] = mapped_column(String(255), default="")
    owner_username: Mapped[str] = mapped_column(String(255), default="")
    photo_file_id: Mapped[str] = mapped_column(String(255), default="")

    __table_args__ = (
        Index(
            "ix_events_agenda",
            "visibility",
            "source_chat_id",
            "date",
            "category",
            "time",
        ),
    )


class Signup(Base):
    __tablename__ = "signups"

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    telegram_name: Mapped[str] = mapped_column(String(130), default="")


class ParticipantDirectory(Base):
    __tablename__ = "participant_directory"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(130), nullable=False)
    last_signup_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    username: Mapped[str] = mapped_column(String(33), default="")


class GroupApplication(Base):
    __tablename__ = "group_applications"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    applicant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    applicant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, approved, rejected, revoked
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GroupApprovalLog(Base):
    __tablename__ = "group_approval_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class KnownGroup(Base):
    __tablename__ = "known_groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)


class EventMessage(Base):
    __tablename__ = "event_messages"

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class AgendaCooldown(Base):
    __tablename__ = "agenda_cooldowns"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_used: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    warning_sent: Mapped[int] = mapped_column(Integer, default=0)


class BlockedUser(Base):
    __tablename__ = "blocked_users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    blocked_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PendingUsernameBan(Base):
    __tablename__ = "pending_username_bans"

    username: Mapped[str] = mapped_column(String(255), primary_key=True)
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    blocked_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resolved_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )


class BlockedGroup(Base):
    __tablename__ = "blocked_groups"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    blocked_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EventExclusion(Base):
    __tablename__ = "event_exclusions"

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    excluded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    excluded_by: Mapped[int] = mapped_column(BigInteger, nullable=False)


class EventAttendance(Base):
    __tablename__ = "event_attendance"

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    attended: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confirmed_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class EventReview(Base):
    __tablename__ = "event_reviews"

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stars: Mapped[int] = mapped_column(Integer, nullable=False)
    review: Mapped[str] = mapped_column(Text, default="")
    event_title: Mapped[str] = mapped_column(String(255), nullable=False)
    organizer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class OrganizerStatReset(Base):
    __tablename__ = "organizer_stat_resets"

    owner_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_cutoff: Mapped[int] = mapped_column(Integer, default=0)
    signup_cutoff: Mapped[int] = mapped_column(Integer, default=0)
    reset_at: Mapped[str] = mapped_column(String(50), nullable=False)