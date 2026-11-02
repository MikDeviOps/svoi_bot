"""База участников (/base) с пагинацией и удалением."""
from html import escape as html_escape
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.owner import IsOwner
from app.db.repo.directory import get_participants_page, delete_participant

router = Router(name="directory")

PAGE_SIZE = 10


@router.message(Command("base"), IsOwner())
async def cmd_base(message: Message, session: AsyncSession):
    total, participants = await get_participants_page(session, 0, PAGE_SIZE)
    await _send_base_page(message, total, participants, 0)


async def _send_base_page(target, total: int, participants, page: int):
    lines = [f"📋 База участников ({total} всего) — стр. {page + 1}", ""]
    for p in participants:
        username = f"@{p.username}" if p.username else ""
        lines.append(f"• {html_escape(p.display_name)} {html_escape(username)} (ID: {p.user_id})")

    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"base:page:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"base:page:{page + 1}"))
    if nav:
        buttons.append(nav)

    # Кнопки удаления для каждого участника
    for p in participants:
        buttons.append([InlineKeyboardButton(
            f"🗑 {p.display_name[:30]}",
            callback_data=f"base:ask:{p.user_id}:{page}",
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    text = "\n".join(lines)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("base:page:"), IsOwner())
async def cb_base_page(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    try:
        page = max(0, int(callback.data.split(":")[2]))
    except (IndexError, ValueError):
        return
    total, participants = await get_participants_page(session, page, PAGE_SIZE)
    await _send_base_page(callback, total, participants, page)


@router.callback_query(F.data.startswith("base:ask:"), IsOwner())
async def cb_base_ask(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    try:
        user_id = int(callback.data.split(":")[2])
        page = max(0, int(callback.data.split(":")[3]))
    except (IndexError, ValueError):
        return

    await callback.message.answer(
        f"Удалить участника {user_id} из каталога?\n"
        "Его записи на встречи и созданные встречи останутся в базе.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("✅ Да, удалить", callback_data=f"base:delete:{user_id}:{page}")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"base:cancel:{page}")],
        ]),
    )


@router.callback_query(F.data.startswith("base:delete:"), IsOwner())
async def cb_base_delete(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    try:
        user_id = int(callback.data.split(":")[2])
        page = max(0, int(callback.data.split(":")[3]))
    except (IndexError, ValueError):
        return

    deleted = await delete_participant(session, user_id)
    if deleted:
        await callback.message.answer(f"✅ Участник {user_id} удалён из каталога.")
    else:
        await callback.message.answer(f"ℹ️ Участник {user_id} не найден в каталоге.")

    total, participants = await get_participants_page(session, page, PAGE_SIZE)
    await _send_base_page(callback, total, participants, page)


@router.callback_query(F.data.startswith("base:cancel:"), IsOwner())
async def cb_base_cancel(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    try:
        page = max(0, int(callback.data.split(":")[2]))
    except (IndexError, ValueError):
        page = 0
    total, participants = await get_participants_page(session, page, PAGE_SIZE)
    await _send_base_page(callback, total, participants, page)