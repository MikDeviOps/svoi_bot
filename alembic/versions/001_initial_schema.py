# alembic/versions/001_initial_schema.py
"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-10-30

"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("time", sa.String(5), nullable=False),
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("conditions", sa.Text, nullable=False),
        sa.Column("capacity", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(50), default="other"),
        sa.Column("source_chat_id", sa.BigInteger, nullable=True, index=True),
        sa.Column("visibility", sa.String(20), default="public"),
        sa.Column("description", sa.Text, default=""),
        sa.Column("owner_name", sa.String(255), default=""),
        sa.Column("source_chat_title", sa.String(255), default=""),
        sa.Column("owner_username", sa.String(255), default=""),
        sa.Column("photo_file_id", sa.String(255), default=""),
    )
    op.create_index("ix_events_agenda", "events", ["visibility", "source_chat_id", "date", "category", "time"])
    op.create_table(
        "signups",
        sa.Column("event_id", sa.BigInteger, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger, primary_key=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("telegram_name", sa.String(130), default=""),
    )
    op.create_table(
        "participant_directory",
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("display_name", sa.String(130), nullable=False),
        sa.Column("last_signup_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("username", sa.String(33), default=""),
    )
    op.create_table(
        "group_applications",
        sa.Column("chat_id", sa.BigInteger, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("applicant_id", sa.BigInteger, nullable=False),
        sa.Column("applicant_name", sa.String(255), nullable=False),
        sa.Column("member_count", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, default=""),
        sa.Column("status", sa.String(20), default="pending"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.BigInteger, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "group_approval_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("actor_id", sa.BigInteger, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "known_groups",
        sa.Column("chat_id", sa.BigInteger, primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
    )
    op.create_table(
        "event_messages",
        sa.Column("event_id", sa.BigInteger, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chat_id", sa.BigInteger, primary_key=True),
        sa.Column("message_id", sa.BigInteger, primary_key=True),
    )
    op.create_table(
        "agenda_cooldowns",
        sa.Column("chat_id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=False),
        sa.Column("warning_sent", sa.Integer, default=0),
    )
    op.create_table(
        "blocked_users",
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("reason", sa.Text, default=""),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_by", sa.BigInteger, nullable=False),
    )
    op.create_table(
        "pending_username_bans",
        sa.Column("username", sa.String(255), primary_key=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_by", sa.BigInteger, nullable=False),
        sa.Column("resolved_user_id", sa.BigInteger, nullable=True, index=True),
    )
    op.create_table(
        "blocked_groups",
        sa.Column("chat_id", sa.BigInteger, primary_key=True),
        sa.Column("reason", sa.Text, default=""),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked_by", sa.BigInteger, nullable=False),
    )
    op.create_table(
        "event_exclusions",
        sa.Column("event_id", sa.BigInteger, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("excluded_by", sa.BigInteger, nullable=False),
    )
    op.create_table(
        "event_attendance",
        sa.Column("event_id", sa.BigInteger, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("attended", sa.Boolean, nullable=False),
        sa.Column("confirmed_by", sa.BigInteger, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "event_reviews",
        sa.Column("event_id", sa.BigInteger, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("stars", sa.Integer, nullable=False),
        sa.Column("review", sa.Text, default=""),
        sa.Column("event_title", sa.String(255), nullable=False),
        sa.Column("organizer_id", sa.BigInteger, nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "organizer_stat_resets",
        sa.Column("owner_id", sa.BigInteger, primary_key=True),
        sa.Column("event_cutoff", sa.Integer, default=0),
        sa.Column("signup_cutoff", sa.Integer, default=0),
        sa.Column("reset_at", sa.String(50), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("organizer_stat_resets")
    op.drop_table("event_reviews")
    op.drop_table("event_attendance")
    op.drop_table("event_exclusions")
    op.drop_table("blocked_groups")
    op.drop_table("pending_username_bans")
    op.drop_table("blocked_users")
    op.drop_table("agenda_cooldowns")
    op.drop_table("event_messages")
    op.drop_table("known_groups")
    op.drop_table("group_approval_log")
    op.drop_table("group_applications")
    op.drop_table("participant_directory")
    op.drop_table("signups")
    op.drop_index("ix_events_agenda", "events")
    op.drop_table("events")