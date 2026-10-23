"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-23

Создаёт: users, known_groups, events, signups, event_messages.
Индексы под афишу и «мои встречи».
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("full_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tg_id", name="pk_users"),
    )

    op.create_table(
        "known_groups",
        sa.Column("chat_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("added_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("chat_id", name="pk_known_groups"),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("address", sa.String(length=250), nullable=False),
        sa.Column("conditions", sa.String(length=500), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="public"),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("source_chat_title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.tg_id"],
            name="fk_events_owner_id_users", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_chat_id"], ["known_groups.chat_id"],
            name="fk_events_source_chat_id_known_groups", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sa.CheckConstraint("capacity BETWEEN 1 AND 1000", name="ck_events_capacity_range"),
        sa.CheckConstraint("visibility IN ('public','chat')", name="ck_events_visibility_values"),
        sa.CheckConstraint("char_length(title) BETWEEN 3 AND 100", name="ck_events_title_len"),
        sa.CheckConstraint("char_length(address) BETWEEN 5 AND 250", name="ck_events_address_len"),
        sa.CheckConstraint(
            "char_length(conditions) BETWEEN 2 AND 500", name="ck_events_conditions_len"
        ),
    )
    op.create_index(
        "ix_events_agenda",
        "events",
        ["visibility", "source_chat_id", "starts_at", "category"],
        unique=False,
    )
    op.create_index(
        "ix_events_owner", "events", ["owner_id", "starts_at"], unique=False
    )

    op.create_table(
        "signups",
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_name", sa.String(length=129), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"],
            name="fk_signups_event_id_events", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.tg_id"],
            name="fk_signups_user_id_users", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", "user_id", name="pk_signups"),
    )

    op.create_table(
        "event_messages",
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"],
            name="fk_event_messages_event_id_events", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "event_id", "chat_id", "message_id", name="pk_event_messages"
        ),
    )


def downgrade() -> None:
    op.drop_table("event_messages")
    op.drop_table("signups")
    op.drop_index("ix_events_owner", table_name="events")
    op.drop_index("ix_events_agenda", table_name="events")
    op.drop_table("events")
    op.drop_table("known_groups")
    op.drop_table("users")