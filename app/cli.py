# app/cli.py
from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import List

from sqlalchemy import text

from app.config import settings
from app.infrastructure.db.engine import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_legacy_conn() -> sqlite3.Connection:
    con = sqlite3.connect(settings.LEGACY_SQLITE_PATH)
    con.row_factory = sqlite3.Row
    return con


async def migrate_table(table_name: str, columns: List[str]) -> int:
    legacy_con = get_legacy_conn()
    rows = legacy_con.execute(
        f"SELECT {', '.join(columns)} FROM {table_name}"
    ).fetchall()
    legacy_con.close()

    if not rows:
        logger.info(f"Table {table_name} is empty. Skipping.")
        return 0

    placeholders = ", ".join([f":{col}" for col in columns])
    insert_stmt = (
        f"INSERT INTO {table_name} ({', '.join(columns)}) "
        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
    )

    success_count = 0
    error_count = 0

    async with engine.begin() as conn:
        for row in rows:
            try:
                data = {col: row[col] for col in columns}
                await conn.execute(text(insert_stmt), data)
                success_count += 1
            except Exception as e:
                logger.error(
                    f"Error inserting into {table_name}: {e} | Row: {dict(row)}"
                )
                error_count += 1

    logger.info(
        f"Migrated {table_name}: {success_count} success, {error_count} errors."
    )
    return success_count


async def main() -> None:
    logger.info("Starting legacy data migration...")

    # Порядок важен из-за внешних ключей
    tables_to_migrate = [
        ("participant_directory", ["user_id", "display_name", "last_signup_at", "username"]),
        ("events", [
            "id", "owner_id", "title", "date", "time", "address", "conditions",
            "capacity", "created_at", "category", "source_chat_id", "visibility",
            "description", "owner_name", "source_chat_title", "owner_username",
            "photo_file_id",
        ]),
        ("signups", ["event_id", "user_id", "created_at", "telegram_name"]),
        ("group_applications", [
            "chat_id", "title", "applicant_id", "applicant_name", "member_count",
            "description", "status", "requested_at", "reviewed_by", "reviewed_at",
        ]),
        ("group_approval_log", ["id", "chat_id", "action", "actor_id", "occurred_at"]),
        ("known_groups", ["chat_id", "title"]),
        ("event_messages", ["event_id", "chat_id", "message_id"]),
        ("agenda_cooldowns", ["chat_id", "user_id", "last_used", "warning_sent"]),
        ("blocked_users", ["user_id", "reason", "blocked_at", "blocked_by"]),
        ("pending_username_bans", [
            "username", "blocked_at", "blocked_by", "resolved_user_id",
        ]),
        ("blocked_groups", ["chat_id", "reason", "blocked_at", "blocked_by"]),
        ("event_exclusions", ["event_id", "user_id", "excluded_at", "excluded_by"]),
        ("event_attendance", [
            "event_id", "user_id", "attended", "confirmed_by", "confirmed_at",
        ]),
        ("event_reviews", [
            "event_id", "user_id", "stars", "review", "event_title",
            "organizer_id", "created_at", "updated_at",
        ]),
        ("organizer_stat_resets", [
            "owner_id", "event_cutoff", "signup_cutoff", "reset_at",
        ]),
    ]

    total_migrated = 0
    for table, cols in tables_to_migrate:
        total_migrated += await migrate_table(table, cols)

    logger.info(f"Migration completed. Total rows migrated: {total_migrated}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())