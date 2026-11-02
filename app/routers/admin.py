"""Админ-панель владельца: /admin, /mine, /groups, /help + callbacks."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Event, GroupApplication, EventMessage, Signup, OrganizerStatReset,
)
from app.services.events import event_with_count, event_card_text
from app.keyboards.events import private_event_keyboard
from app.filters.owner import IsOwner
from app.config import settings
from app.utils.time import now_msk
from app.db.base import utcnow

router = Router(name="admin")


@router.message(Command("mine"))
async def cmd_mine(message: Message, session: AsyncSession):
    if message.chat.type != "private":
        await message.reply_text("Команда /mine доступна в личном чате с ботом.")
        return

    stmt = (
        select(Event)
        .where(Event.owner_id == message.from_user.id, Event.starts_at > now_msk())
        .order_by(Event.starts_at.asc())
        .limit(30)
    )
    events = (await session.execute(stmt)).scalars().all()

    if not events:
        await message.reply_text("У вас пока нет предстоящих встреч. /create")
        return

    await message.reply_text("Ваши встречи:")
    for event_model in events:
        event = await event_with_count(session, event_model.id)
        text = event_card_text(event, private_details=True)
        if event["photo_file_id"]:
            await message.answer_photo(photo=event["photo_file_id"], caption=text[:1024], reply_markup=private_event_keyboard(event, message.from_user.id))
        else:
            await message.answer(text, reply_markup=private_event_keyboard(event, message.from_user.id))


@router.message(Command("admin"), IsOwner())
async def cmd_admin(message: Message, session: AsyncSession):
    if message.chat.type != "private":
        await message.reply_text("⛔ Панель доступна только в личном чате.")
        return

    await message.reply_text(
        "🛡 Управление платформой СВОИ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏘 Зарегистрированные группы", callback_data="owner:approvedgroups")],
            [InlineKeyboardButton(text="📋 Все заявки на регистрацию", callback_data="owner:applications")],
            [InlineKeyboardButton(text="🔄 Обнулить статистику", callback_data="statreset:list:0")],
        ]),
    )

    stmt = select(Event).where(Event.starts_at > now_msk()).order_by(Event.id.desc()).limit(30)
    events = (await session.execute(stmt)).scalars().all()
    if not events:
        return

    await message.reply_text("🛡 Управление встречами (последние 30):")
    for event_model in events:
        event = await event_with_count(session, event_model.id)
        text = (
            f"№{event['id']} · {event['title']}\n"
            f"🏘 {event['source_chat_title'] or 'из общей афиши'} · {event['starts_at'].strftime('%d.%m.%Y %H:%M')}\n"
            f"👤 {event['owner_name']}"
        )
        await message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👥 Участники", callback_data=f"adminpeople:{event['id']}")],
                [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"deleteask:{event['id']}")],
            ]),
        )


@router.message(Command("groups"), IsOwner())
async def cmd_groups(message: Message, session: AsyncSession):
    stmt = (
        select(GroupApplication)
        .where(GroupApplication.status == "pending")
        .order_by(GroupApplication.requested_at.desc())
    )
    applications = (await session.execute(stmt)).scalars().all()

    if not applications:
        await message.reply_text("📋 Заявок на регистрацию пока нет.")
        return

    await message.reply_text(f"📋 Заявки на регистрацию ({len(applications)}):")
    for app in applications:
        text = (
            f"🏘 {app.title}\n"
            f"👥 {app.member_count} участников\n"
            f"👤 {app.applicant_name}\n"
            f"ID: {app.chat_id}\n"
            f"📝 {app.description or 'без описания'}"
        )
        await message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"groupreview:{app.chat_id}:approve")],
                [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"groupreview:{app.chat_id}:reject")],
            ]),
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.reply_text(
        "❓ Помощь по боту СВОИ:\n\n"
        "📅 /vstrechi — афиша встреч\n"
        "➕ /create — создать встречу\n"
        "📋 /mine — мои встречи\n"
        "⭐ /rating — моя активность\n"
        "🏠 /grouprating — активность чата\n"
        "📊 /organizer — история организаторов\n"
        "📝 /review — оставить отзыв\n\n"
        "Для записи на встречи необходимо вступить в главную группу СВОИ.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Вступить в группу", url=settings.support_invite_fallback)]
        ]),
    )


@router.callback_query(F.data == "owner:approvedgroups", IsOwner())
async def cb_owner_approved_groups(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    stmt = select(GroupApplication).where(GroupApplication.status == "approved").order_by(GroupApplication.title)
    groups = (await session.execute(stmt)).scalars().all()

    if not groups:
        await callback.message.answer("🏘 Зарегистрированных групп пока нет.")
        return

    await callback.message.answer(f"🏘 Зарегистрированные группы: {len(groups)}")
    for group in groups:
        text = (
            f"✅ {group.title}\n"
            f"👥 {group.member_count} участников\n"
            f"👤 {group.applicant_name}\n"
            f"ID: {group.chat_id}"
        )
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚫 Отозвать доступ", callback_data=f"groupreview:{group.chat_id}:revoke")]
            ]),
        )


@router.callback_query(F.data == "owner:applications", IsOwner())
async def cb_owner_applications(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("📋 Все заявки и управление доступом: /groups")


@router.callback_query(F.data.startswith("groupreview:"), IsOwner())
async def cb_group_review(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    try:
        chat_id = int(callback.data.split(":")[1])
        action = callback.data.split(":")[2]
    except (IndexError, ValueError):
        await callback.message.answer("Неверный формат.")
        return

    stmt = select(GroupApplication).where(GroupApplication.chat_id == chat_id, GroupApplication.status == "pending")
    application = (await session.execute(stmt)).scalar_one_or_none()
    if not application:
        await callback.message.answer("Заявка не найдена или уже рассмотрена.")
        return

    now = utcnow()
    if action == "approve":
        application.status = "approved"
        application.reviewed_by = callback.from_user.id
        application.reviewed_at = now
        await callback.message.answer(f"✅ Группа «{application.title}» зарегистрирована.")
    elif action == "reject":
        application.status = "rejected"
        application.reviewed_by = callback.from_user.id
        application.reviewed_at = now
        await callback.message.answer(f"❌ Заявка группы «{application.title}» отклонена.")
    elif action == "revoke":
        application.status = "revoked"
        application.reviewed_by = callback.from_user.id
        application.reviewed_at = now
        await callback.message.answer(f"🚫 Доступ группы «{application.title}» отозван.")


@router.callback_query(F.data.startswith("adminpeople:"), IsOwner())
async def cb_admin_people(callback: CallbackQuery, session: AsyncSession):
    """Переиспользуем manage_participants из management.py."""
    await callback.answer()
    try:
        event_id = int(callback.data.split(":")[1])
        page = int(callback.data.split(":")[2]) if len(callback.data.split(":")) > 2 else 0
    except (IndexError, ValueError):
        await callback.message.answer("Неверный формат.")
        return

    from app.routers.management import _render_manage_participants
    await _render_manage_participants(callback.message, session, event_id, page)


@router.callback_query(F.data.startswith("statreset:"), IsOwner())
async def cb_statreset(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if callback.message.chat.type != "private":
        await callback.message.answer("⛔ Недостаточно прав.")
        return

    parts = callback.data.split(":")

    if parts[1] == "list":
        page = max(0, int(parts[2])) if len(parts) > 2 else 0
        stmt = (
            select(Event.owner_id, func.max(Event.owner_name).label("name"), func.count(Event.id).label("total"))
            .group_by(Event.owner_id)
            .order_by(func.count(Event.id).desc())
            .limit(8)
            .offset(page * 8)
        )
        rows = (await session.execute(stmt)).all()
        count = (await session.execute(select(func.count(func.distinct(Event.owner_id))))).scalar() or 0

        buttons = [[InlineKeyboardButton(text=f"👤 {r.name or r.owner_id}", callback_data=f"statreset:ask:{r.owner_id}")] for r in rows]
        nav = []
        if page:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"statreset:list:{page - 1}"))
        if (page + 1) * 8 < count:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"statreset:list:{page + 1}"))
        if nav:
            buttons.append(nav)
        buttons.append([InlineKeyboardButton(text="🔄 Всех организаторов", callback_data="statreset:allask")])

        await callback.message.edit_text(
            "🔄 Обнуление статистики\nВыберите организатора. Встречи и записи сохранятся.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        return

    if parts[1] in ("ask", "allask"):
        all_users = parts[1] == "allask"
        target = "всех организаторов" if all_users else f"организатора ID {int(parts[2])}"
        confirm = "statreset:allconfirm" if all_users else f"statreset:confirm:{int(parts[2])}"
        await callback.message.edit_text(
            f"Обнулить показатели {target}?\nВстречи и участники останутся в базе.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, обнулить", callback_data=confirm)],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="statreset:cancel")],
            ]),
        )
        return

    if parts[1] == "cancel":
        await callback.message.edit_text("Обнуление отменено. Данные не изменены.")
        return

    if parts[1] in ("confirm", "allconfirm"):
        if parts[1] == "confirm":
            ids = [int(parts[2])]
        else:
            ids = [r[0] for r in (await session.execute(select(Event.owner_id).distinct())).all()]

        now = utcnow()
        for uid in ids:
            max_event = (await session.execute(
                select(func.coalesce(func.max(Event.id), 0)).where(Event.owner_id == uid)
            )).scalar() or 0
            max_signup = (await session.execute(
                select(func.coalesce(func.max(Signup.id), 0))
                .select_from(Signup)
                .join(Event, Event.id == Signup.event_id)
                .where(Event.owner_id == uid)
            )).scalar() or 0

            stmt = select(OrganizerStatReset).where(OrganizerStatReset.owner_id == uid)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                existing.event_cutoff = max_event
                existing.signup_cutoff = max_signup
                existing.reset_at = now
            else:
                session.add(OrganizerStatReset(
                    owner_id=uid, event_cutoff=max_event, signup_cutoff=max_signup, reset_at=now,
                ))

        await session.commit()
        await callback.message.edit_text(
            f"✅ Статистика обнулена: {len(ids)} организаторов.\nИстория встреч и записи участников сохранены."
        )