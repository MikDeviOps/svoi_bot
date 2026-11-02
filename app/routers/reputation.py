"""Прозрачная статистика активности без выдуманных оценок качества."""
from html import escape as html_escape
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, Signup, EventAttendance, ParticipantDirectory, OrganizerStatReset
from app.utils.time import now_msk

router = Router(name="reputation")

ORGANIZERS_PAGE_SIZE = 8


# --- /rating ---
@router.message(Command("rating"))
async def cmd_rating(message: Message, session: AsyncSession):
    user_id = message.from_user.id

    created = (await session.execute(select(func.count(Event.id)).where(Event.owner_id == user_id))).scalar() or 0
    signed = (await session.execute(select(func.count(Signup.id)).where(Signup.user_id == user_id))).scalar() or 0
    attended = (await session.execute(
        select(func.count(EventAttendance.user_id)).where(
            EventAttendance.user_id == user_id, EventAttendance.attended == True
        )
    )).scalar() or 0

    await message.answer(
        "⭐ Активность в СВОИ\n"
        f"Создано встреч: {created}\n"
        f"Текущих записей: {signed}\n"
        f"Подтверждено посещений: {attended}\n\n"
        "Это статистика, не оценка человека. Посещения засчитываются только после подтверждения."
    )


# --- /grouprating ---
@router.message(Command("grouprating"))
async def cmd_grouprating(message: Message, session: AsyncSession):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Команда /grouprating доступна в группе.")
        return

    chat_id = message.chat.id
    created = (await session.execute(
        select(func.count(Event.id)).where(Event.source_chat_id == chat_id)
    )).scalar() or 0
    signed = (await session.execute(
        select(func.count(Signup.id))
        .select_from(Signup)
        .join(Event, Event.id == Signup.event_id)
        .where(Event.source_chat_id == chat_id)
    )).scalar() or 0

    await message.answer(
        f"🏠 Активность чата «{message.chat.title}»\n"
        f"Создано встреч: {created}\n"
        f"Текущих записей: {signed}\n\n"
        "Это статистика активности, а не оценка качества сообщества."
    )


# --- /organizer ---
async def _organizer_rows(session: AsyncSession, page: int = 0):
    total = (await session.execute(select(func.count(func.distinct(Event.owner_id))))).scalar() or 0

    cutoff_sub = select(OrganizerStatReset.event_cutoff).where(OrganizerStatReset.owner_id == Event.owner_id).scalar_subquery()
    stmt = (
        select(
            Event.owner_id,
            func.max(Event.owner_name).label("name"),
            func.max(Event.owner_username).label("username"),
            func.sum(func.case((Event.id > func.coalesce(cutoff_sub, 0), 1), else_=0)).label("total"),
        )
        .group_by(Event.owner_id)
        .order_by(func.sum(func.case((Event.id > func.coalesce(cutoff_sub, 0), 1), else_=0)).desc(), Event.owner_id)
        .limit(ORGANIZERS_PAGE_SIZE)
        .offset(page * ORGANIZERS_PAGE_SIZE)
    )
    result = await session.execute(stmt)
    return total, result.all()


def _organizer_keyboard(rows, page: int, total: int) -> InlineKeyboardMarkup:
    buttons = []
    for row in rows:
        name = row.name or (f"@{row.username}" if row.username else str(row.owner_id))
        buttons.append([InlineKeyboardButton(
            f"👤 {name[:35]} · {row.total} встреч",
            callback_data=f"org:profile:{row.owner_id}:{page}",
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Назад", callback_data=f"org:list:{page - 1}"))
    if (page + 1) * ORGANIZERS_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Далее ▶️", callback_data=f"org:list:{page + 1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("organizer"))
async def cmd_organizer(message: Message, session: AsyncSession):
    if message.chat.type != "private":
        await message.answer("История организаторов доступна в личном чате с ботом.")
        return

    total, rows = await _organizer_rows(session, 0)
    if not rows:
        await message.answer("Пока никто не создавал встречи.")
        return

    await message.answer(
        f"📊 История организаторов\nВсего организаторов: {total}\nВыберите человека:",
        reply_markup=_organizer_keyboard(rows, 0, total),
    )


# --- Callbacks ---
@router.callback_query(F.data.startswith("org:list:"))
async def cb_org_list(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if callback.message.chat.type != "private":
        return
    try:
        page = max(0, int(callback.data.split(":")[2]))
    except (IndexError, ValueError):
        return

    total, rows = await _organizer_rows(session, page)
    if not rows and page:
        page = 0
        total, rows = await _organizer_rows(session, page)

    await callback.message.edit_text(
        f"📊 История организаторов\nВсего организаторов: {total}\nВыберите человека:",
        reply_markup=_organizer_keyboard(rows, page, total),
    )


@router.callback_query(F.data.startswith("org:profile:"))
async def cb_org_profile(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if callback.message.chat.type != "private":
        return
    try:
        owner_id = int(callback.data.split(":")[2])
        page = max(0, int(callback.data.split(":")[3]))
    except (IndexError, ValueError):
        return

    now = now_msk()
    today = now.date().isoformat()
    clock = now.strftime("%H:%M")

    # Получаем cutoff
    stmt = select(OrganizerStatReset).where(OrganizerStatReset.owner_id == owner_id)
    reset = (await session.execute(stmt)).scalar_one_or_none()
    event_cutoff = reset.event_cutoff if reset else 0

    # Считаем статистику
    stmt = select(
        func.max(Event.owner_name).label("name"),
        func.max(Event.owner_username).label("username"),
        func.sum(func.case((Event.id > event_cutoff, 1), else_=0)).label("total"),
        func.sum(func.case(
            (
                (Event.id > event_cutoff) & (
                    (func.date(Event.starts_at) > today) |
                    ((func.date(Event.starts_at) == today) & (func.time(Event.starts_at) > clock))
                ),
                1
            ),
            else_=0,
        )).label("upcoming"),
    ).where(Event.owner_id == owner_id)
    row = (await session.execute(stmt)).one()

    if not row.name:
        await callback.message.edit_text(
            "История организатора не найдена.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton("◀️ К списку", callback_data=f"org:list:{page}")
            ]]),
        )
        return

    # Считаем записи
    signup_cutoff = reset.signup_cutoff if reset else 0
    signed = (await session.execute(
        select(func.count(Signup.id))
        .select_from(Signup)
        .join(Event, Event.id == Signup.event_id)
        .where(Event.owner_id == owner_id, Signup.id > signup_cutoff)
    )).scalar() or 0

    name = html_escape(row.name or "Организатор")
    username = (row.username or "").lstrip("@")
    mention = f'<a href="tg://user?id={owner_id}">{name}</a>'
    handle = f" (@{html_escape(username)})" if username else ""
    upcoming = row.upcoming or 0
    total = row.total or 0

    await callback.message.edit_text(
        f"📊 История организатора\n\n"
        f"👤 {mention}{handle}\n\n"
        f"📅 Всего создано встреч: {total}\n"
        f"🟢 Предстоящих встреч: {upcoming}\n"
        f"🕒 Прошедших по дате: {total - upcoming}\n"
        f"👥 Всего записей на встречи: {signed}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("👥 Список участников", callback_data=f"org:people:{owner_id}:{page}:0")],
            [InlineKeyboardButton("◀️ К списку", callback_data=f"org:list:{page}")],
        ]),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("org:people:"))
async def cb_org_people(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if callback.message.chat.type != "private":
        return
    try:
        owner_id = int(callback.data.split(":")[2])
        origin_page = max(0, int(callback.data.split(":")[3]))
        people_page = max(0, int(callback.data.split(":")[4]))
    except (IndexError, ValueError):
        return

    page_size = 15

    total = (await session.execute(
        select(func.count(func.distinct(Signup.user_id)))
        .select_from(Signup)
        .join(Event, Event.id == Signup.event_id)
        .where(Event.owner_id == owner_id)
    )).scalar() or 0

    stmt = (
        select(
            Signup.user_id,
            func.coalesce(
                func.max(func.nullif(Signup.telegram_name, "")),
                func.max(func.nullif(ParticipantDirectory.display_name, "")),
                "Участник",
            ).label("name"),
            func.max(func.nullif(ParticipantDirectory.username, "")).label("username"),
            func.count(Signup.id).label("signups_count"),
        )
        .select_from(Signup)
        .join(Event, Event.id == Signup.event_id)
        .outerjoin(ParticipantDirectory, ParticipantDirectory.user_id == Signup.user_id)
        .where(Event.owner_id == owner_id)
        .group_by(Signup.user_id)
        .order_by(func.count(Signup.id).desc(), Signup.user_id)
        .limit(page_size)
        .offset(people_page * page_size)
    )
    rows = (await session.execute(stmt)).all()

    lines = [f"👥 Список участников организатора\nВсего человек: {total}\n"]
    for i, person in enumerate(rows, start=people_page * page_size + 1):
        uid = int(person.user_id)
        name = html_escape(str(person.name)[:70])
        lines.append(f"{i}. <a href=\"tg://user?id={uid}\">{name}</a> — записей: {person.signups_count}")
    if not rows:
        lines.append("Записей на встречи пока нет.")

    buttons = []
    nav = []
    if people_page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"org:people:{owner_id}:{origin_page}:{people_page - 1}"))
    if (people_page + 1) * page_size < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"org:people:{owner_id}:{origin_page}:{people_page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("◀️ К организатору", callback_data=f"org:profile:{owner_id}:{origin_page}")])
    buttons.append([InlineKeyboardButton("📋 К списку", callback_data=f"org:list:{origin_page}")])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        disable_web_page_preview=True,
    )