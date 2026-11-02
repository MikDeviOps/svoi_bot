"""Глобальная модерация: /blockuser, /unblockuser, /blockgroup, /unblockgroup, /blocks + русский «бан/разбан»."""
import re
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.owner import IsOwner
from app.config import settings
from app.db.models import BlockedUser, BlockedGroup, ParticipantDirectory, Event, PendingUsernameBan
from app.db.base import utcnow

router = Router(name="moderation")


# --- Команды модерации ---
@router.message(Command("blockuser"), IsOwner())
async def cmd_blockuser(message: Message, session: AsyncSession):
    if not message.text or len(message.text.split()) < 2:
        await message.reply_text("Формат: /blockuser ID [причина]")
        return

    try:
        target = int(message.text.split()[1])
    except ValueError:
        await message.reply_text("Укажите числовой Telegram ID.")
        return

    reason = " ".join(message.text.split()[2:])[:300] if len(message.text.split()) > 2 else ""

    if target in settings.owners:
        await message.reply_text("Нельзя заблокировать владельца платформы.")
        return

    now = utcnow()
    stmt = select(BlockedUser).where(BlockedUser.user_id == target)
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing:
        existing.reason = reason
        existing.blocked_at = now
        existing.blocked_by = message.from_user.id
    else:
        session.add(BlockedUser(user_id=target, reason=reason, blocked_at=now, blocked_by=message.from_user.id))

    await message.reply_text(f"⛔ Заблокирован: {target}")


@router.message(Command("unblockuser"), IsOwner())
async def cmd_unblockuser(message: Message, session: AsyncSession):
    if not message.text or len(message.text.split()) < 2:
        await message.reply_text("Формат: /unblockuser ID")
        return

    try:
        target = int(message.text.split()[1])
    except ValueError:
        await message.reply_text("Укажите числовой Telegram ID.")
        return

    result = await session.execute(delete(BlockedUser).where(BlockedUser.user_id == target))
    # Также чистим pending_username_bans по resolved_user_id
    await session.execute(delete(PendingUsernameBan).where(PendingUsernameBan.resolved_user_id == target))

    if result.rowcount > 0:
        await message.reply_text(f"✅ Разблокирован: {target}")
    else:
        await message.reply_text(f"ℹ️ Пользователь {target} не был заблокирован.")


@router.message(Command("blockgroup"), IsOwner())
async def cmd_blockgroup(message: Message, session: AsyncSession):
    if not message.text or len(message.text.split()) < 2:
        await message.reply_text("Формат: /blockgroup ID [причина]")
        return

    try:
        target = int(message.text.split()[1])
    except ValueError:
        await message.reply_text("Укажите числовой Telegram ID.")
        return

    reason = " ".join(message.text.split()[2:])[:300] if len(message.text.split()) > 2 else ""
    now = utcnow()

    stmt = select(BlockedGroup).where(BlockedGroup.chat_id == target)
    existing = (await session.execute(stmt)).scalar_one_or_none()

    if existing:
        existing.reason = reason
        existing.blocked_at = now
        existing.blocked_by = message.from_user.id
    else:
        session.add(BlockedGroup(chat_id=target, reason=reason, blocked_at=now, blocked_by=message.from_user.id))

    await message.reply_text(f"⛔ Заблокирована группа: {target}")


@router.message(Command("unblockgroup"), IsOwner())
async def cmd_unblockgroup(message: Message, session: AsyncSession):
    if not message.text or len(message.text.split()) < 2:
        await message.reply_text("Формат: /unblockgroup ID")
        return

    try:
        target = int(message.text.split()[1])
    except ValueError:
        await message.reply_text("Укажите числовой Telegram ID.")
        return

    result = await session.execute(delete(BlockedGroup).where(BlockedGroup.chat_id == target))
    if result.rowcount > 0:
        await message.reply_text(f"✅ Разблокирована группа: {target}")
    else:
        await message.reply_text(f"ℹ️ Группа {target} не была заблокирована.")


@router.message(Command("blocks"), IsOwner())
async def cmd_blocks(message: Message, session: AsyncSession):
    users = (await session.execute(
        select(BlockedUser).order_by(BlockedUser.blocked_at.desc()).limit(30)
    )).scalars().all()

    groups = (await session.execute(
        select(BlockedGroup).order_by(BlockedGroup.blocked_at.desc()).limit(30)
    )).scalars().all()

    lines = ["🚫 Блокировки СВОИ", "", "Пользователи:"]
    lines += [f"• {u.user_id} — {u.reason or 'без причины'}" for u in users] or ["Нет"]
    lines += ["", "Группы:"]
    lines += [f"• {g.chat_id} — {g.reason or 'без причины'}" for g in groups] or ["Нет"]

    await message.reply_text("\n".join(lines))


# --- Русский «бан/разбан @nick|id» (высокий приоритет) ---
@router.message(F.text.regexp(r"(?i)^(?:бан|разбан)\s+(?:@[A-Za-z0-9_]{5,32}|[0-9]{5,20})\s*$"), IsOwner())
async def russian_ban_message(message: Message, session: AsyncSession):
    match = re.fullmatch(r"(бан|разбан)\s+(@[A-Za-z0-9_]{5,32}|[0-9]{5,20})\s*", message.text or "", re.I)
    if not match:
        return

    verb, identity = match.group(1).lower(), match.group(2)
    username = identity[1:].lower() if identity.startswith("@") else None
    now = utcnow()

    target = None
    if username:
        # Ищем ID по username в каталоге и в истории организаторов
        candidates = set()
        participants = (await session.execute(
            select(ParticipantDirectory.user_id).where(ParticipantDirectory.username == username)
        )).scalars().all()
        candidates.update(int(p) for p in participants)

        owners = (await session.execute(
            select(Event.owner_id).where(func_lower_username(Event.owner_username) == username).distinct()
        )).scalars().all()
        candidates.update(int(o) for o in owners)

        # Проверяем pending
        pending = (await session.execute(
            select(PendingUsernameBan.resolved_user_id).where(PendingUsernameBan.username == username)
        )).scalar_one_or_none()
        if pending:
            candidates.add(int(pending))

        if len(candidates) > 1:
            await message.reply_text("⚠️ Ник встречается у нескольких пользователей в истории. Укажите Telegram ID.")
            return
        target = next(iter(candidates), None)
    else:
        target = int(identity)

    if verb == "бан":
        if target is not None and target in settings.owners:
            await message.reply_text("⛔ Владельца СВОИ заблокировать нельзя.")
            return

        if username:
            # Сохраняем pending ban
            stmt = select(PendingUsernameBan).where(PendingUsernameBan.username == username)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.blocked_at = now
                existing.blocked_by = message.from_user.id
                if target is not None:
                    existing.resolved_user_id = target
            else:
                session.add(PendingUsernameBan(
                    username=username, blocked_at=now, blocked_by=message.from_user.id, resolved_user_id=target,
                ))

        if target is not None:
            stmt = select(BlockedUser).where(BlockedUser.user_id == target)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.reason = "Блокировка владельцем"
                existing.blocked_at = now
                existing.blocked_by = message.from_user.id
            else:
                session.add(BlockedUser(
                    user_id=target, reason="Блокировка владельцем", blocked_at=now, blocked_by=message.from_user.id,
                ))

        response = (
            f"⛔ Пользователь {identity} забанен в СВОИ."
            if target is not None
            else f"⛔ Ник {identity} добавлен в чёрный список. Бан закрепится по ID при первом появлении пользователя."
        )
    else:
        if username:
            await session.execute(delete(PendingUsernameBan).where(PendingUsernameBan.username == username))
        changed = 0
        if target is not None:
            result = await session.execute(delete(BlockedUser).where(BlockedUser.user_id == target))
            changed = result.rowcount
            await session.execute(delete(PendingUsernameBan).where(PendingUsernameBan.resolved_user_id == target))

        response = (
            f"✅ Пользователь {identity} разбанен в СВОИ."
            if username or changed
            else f"ℹ️ Пользователь {identity} не был заблокирован."
        )

    await message.reply_text(response)


def func_lower_username(col):
    """SQL LOWER для сравнения username без учёта регистра."""
    from sqlalchemy import func
    return func.lower(col)