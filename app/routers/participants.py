"""Запись на встречи, отмена, просмотр участников + уведомления групп."""
from html import escape as html_escape
from aiogram import Router, F, Bot
from aiogram.enums import ChatType
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.db.models import Event, Signup, EventExclusion, ParticipantDirectory, BlockedUser
from app.services.events import event_with_count, refresh_event_messages
from app.keyboards.events import event_keyboard
from app.services.support import has_support_membership, subscription_prompt
from app.config import settings
from app.utils.time import now_msk
from app.utils.html import safe_html

logger = logging.getLogger(__name__)

router = Router(name="participants")


# --------------------------------------------------------------------------- #
# Вспомогательные функции
# --------------------------------------------------------------------------- #
async def can_access_event(session: AsyncSession, bot: Bot, event: dict, user_id: int, chat_id: int | None = None) -> bool:
    """Проверка доступа к встрече (видимость + членство в чате)."""
    stmt = select(BlockedUser.user_id).where(BlockedUser.user_id == user_id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        return False
    
    if event["visibility"] == "public":
        return True
    
    if event["visibility"] == "chat":
        source_chat_id = event.get("source_chat_id")
        if not source_chat_id:
            return False
        
        try:
            member = await bot.get_chat_member(chat_id=source_chat_id, user_id=user_id)
            return member.status in ("creator", "administrator", "member", "restricted")
        except Exception:
            return False
    
    return False


def event_visible_in_current_group(event: dict, chat_type: str, chat_id: int | None) -> bool:
    """Видима ли встреча в текущем чате."""
    if event["visibility"] == "public":
        return True
    if chat_type == ChatType.PRIVATE:
        return True
    return (
        chat_type in (ChatType.GROUP, ChatType.SUPERGROUP)
        and event.get("source_chat_id") == chat_id
    )


def event_origin_label(event: dict, chat_type: str, chat_id: int | None) -> str:
    """Описание происхождения встречи."""
    source_id = event.get("source_chat_id")
    source_title = (event.get("source_chat_title") or "").strip()
    
    if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if source_id is not None and int(source_id) == chat_id:
            return "нашего чата"
        return "другого чата" if source_id is not None else "из общей афиши"
    
    if source_title:
        return f"чата «{safe_html(source_title)}»"
    return "из общей афиши"


def organizer_label(event: dict) -> str:
    """HTML-безопасное имя организатора."""
    username = (event.get("owner_username") or "").strip().lstrip("@")
    name = (event.get("owner_name") or "").strip()
    
    if username:
        return f"@{safe_html(username)}"
    return safe_html(name or "не указан")


async def notify_source_group(
    bot: Bot,
    event: dict,
    user_id: int,
    user_name: str,
    available: int,
    *,
    joined: bool,
) -> None:
    """Уведомление группы-организатора о записи/отмене."""
    source_chat_id = event.get("source_chat_id")
    if source_chat_id is None:
        return
    
    mention = f'<a href="tg://user?id={user_id}">{safe_html(user_name)}</a>'
    action = "записался(ась)" if joined else "отменил(а) запись"
    icon = "✅" if joined else "❌"
    text = (
        f'{icon} {mention} {action} на встречу «{safe_html(event["title"])}».\n'
        f'👥 Свободно мест: {available}.'
    )
    
    try:
        await bot.send_message(chat_id=source_chat_id, text=text, disable_web_page_preview=True)
    except TelegramAPIError as exc:
        logger.warning("Could not notify source group for event %s: %s", event["id"], exc)


# --------------------------------------------------------------------------- #
# Запись на встречу
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("join:"))
async def cb_join(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    """Запись на встречу."""
    await callback.answer()
    
    try:
        event_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.message.answer("Неверная встреча.")
        return
    
    if not await has_support_membership(bot, callback.from_user.id):
        await callback.message.answer(
            "🔒 Для записи на встречи необходимо вступить в главную группу СВОИ.",
            reply_markup=subscription_prompt()
        )
        return
    
    event = await event_with_count(session, event_id)
    if not event:
        await callback.message.answer("Встреча не найдена.")
        return
    
    if not await can_access_event(session, bot, event, callback.from_user.id, callback.message.chat.id):
        await callback.message.answer("Эта встреча доступна только участникам чата-организатора.")
        return
    
    stmt = select(Signup.id).where(Signup.event_id == event_id, Signup.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        available = max(0, event["capacity"] - event["booked"])
        await callback.message.answer(f"Вы уже записаны на эту встречу. Свободно мест: {available}.")
        return
    
    stmt = select(EventExclusion.user_id).where(EventExclusion.event_id == event_id, EventExclusion.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        await callback.message.answer("⛔ Организатор исключил вас из этой встречи. Повторная запись недоступна.")
        return
    
    if event["starts_at"] <= now_msk():
        await callback.message.answer("Встреча уже началась или прошла.")
        return
    
    if event["booked"] >= event["capacity"]:
        await callback.message.answer("К сожалению, свободных мест уже нет.")
        return
    
    # Блокируем строку события
    stmt = select(Event).where(Event.id == event_id).with_for_update()
    result = await session.execute(stmt)
    locked_event = result.scalar_one_or_none()
    if not locked_event:
        await callback.message.answer("Встреча уже удалена.")
        return
    
    stmt = select(func.count(Signup.id)).where(Signup.event_id == event_id)
    result = await session.execute(stmt)
    current_count = result.scalar()
    
    if current_count >= locked_event.capacity:
        await callback.message.answer("К сожалению, свободных мест уже нет.")
        return
    
    telegram_name = f"@{callback.from_user.username}" if callback.from_user.username else (callback.from_user.full_name or "Имя не указано")
    new_signup = Signup(
        event_id=event_id,
        user_id=callback.from_user.id,
        telegram_name=telegram_name[:129]
    )
    session.add(new_signup)
    
    stmt = select(ParticipantDirectory).where(ParticipantDirectory.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    participant = result.scalar_one_or_none()
    
    if participant:
        participant.display_name = callback.from_user.full_name or "Участник"
        participant.username = callback.from_user.username or ""
        participant.last_signup_at = now_msk()
    else:
        session.add(ParticipantDirectory(
            user_id=callback.from_user.id,
            display_name=callback.from_user.full_name or "Участник",
            username=callback.from_user.username or "",
            last_signup_at=now_msk()
        ))
    
    await session.commit()
    
    await refresh_event_messages(bot, event_id)
    
    available = max(0, locked_event.capacity - current_count - 1)
    
    # Уведомление в группу-организатор
    user_name = callback.from_user.full_name or str(callback.from_user.id)
    await notify_source_group(bot, event, callback.from_user.id, user_name, available, joined=True)
    
    # Ответ пользователю
    mention = f'<a href="tg://user?id={callback.from_user.id}">{safe_html(user_name)}</a>'
    origin = event_origin_label(event, callback.message.chat.type, callback.message.chat.id)
    result_text = (
        f'✅ {mention} присоединился(ась) к встрече {origin} «{safe_html(event["title"])}».\n'
        f'👤 Организатор: {organizer_label(event)}\n'
        f'👥 Свободно мест: {available}.'
    )
    await callback.message.answer(result_text, disable_web_page_preview=True)


# --------------------------------------------------------------------------- #
# Отмена записи
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel_signup(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    """Отмена записи на встречу."""
    await callback.answer()
    
    try:
        event_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.message.answer("Неверная встреча.")
        return
    
    event = await event_with_count(session, event_id)
    if not event:
        await callback.message.answer("Встреча не найдена.")
        return
    
    stmt = select(Signup.id).where(Signup.event_id == event_id, Signup.user_id == callback.from_user.id)
    result = await session.execute(stmt)
    if not result.scalar_one_or_none():
        await callback.message.answer("Вы не записаны на эту встречу.")
        return
    
    stmt = delete(Signup).where(Signup.event_id == event_id, Signup.user_id == callback.from_user.id)
    await session.execute(stmt)
    await session.commit()
    
    await refresh_event_messages(bot, event_id)
    
    available = max(0, event["capacity"] - event["booked"] + 1)
    
    # Уведомление в группу-организатор
    user_name = callback.from_user.full_name or str(callback.from_user.id)
    await notify_source_group(bot, event, callback.from_user.id, user_name, available, joined=False)
    
    # Ответ пользователю
    mention = f'<a href="tg://user?id={callback.from_user.id}">{safe_html(user_name)}</a>'
    origin = event_origin_label(event, callback.message.chat.type, callback.message.chat.id)
    result_text = (
        f'❌ {mention} отменил(а) запись на встречу {origin} «{safe_html(event["title"])}».\n'
        f'👤 Организатор: {organizer_label(event)}\n'
        f'👥 Свободно мест: {available}.'
    )
    await callback.message.answer(result_text, disable_web_page_preview=True)


# --------------------------------------------------------------------------- #
# Просмотр участников
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("participants:"))
async def cb_participants(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    """Просмотр списка участников."""
    await callback.answer()
    
    try:
        event_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.message.answer("Неверная встреча.")
        return
    
    event = await event_with_count(session, event_id)
    if not event:
        await callback.message.answer("Встреча не найдена.")
        return
    
    if not await can_access_event(session, bot, event, callback.from_user.id, callback.message.chat.id):
        await callback.message.answer("Список доступен только участникам чата-организатора.")
        return
    
    stmt = select(Signup.telegram_name).where(Signup.event_id == event_id).order_by(Signup.created_at.asc())
    result = await session.execute(stmt)
    names = [row[0] for row in result.all()]
    
    count = len(names)
    heading = (
        f"👤 @{callback.from_user.username or callback.from_user.full_name}, запросил(а) список.\n"
        f"👥 Участники встречи «{safe_html(event['title'])}»\n"
        f"Записано: {count}/{event['capacity']}"
    )
    
    if not names:
        await callback.message.answer(f"{heading}\nПока никто не записался.")
        return
    
    text = heading
    for name in names:
        line = f"\n• {safe_html(name or 'Имя не указано')}"
        if len(text) + len(line) > 3800:
            await callback.message.answer(text)
            text = "👥 Участники (продолжение)"
        text += line
    
    await callback.message.answer(text)