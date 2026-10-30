# app/infrastructure/telegram/routers/reputation.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from app.application.services.reputation_service import ReputationService
from app.infrastructure.telegram.keyboards import (
    organizers_keyboard,
    organizer_profile_keyboard,
    organizer_people_keyboard,
)
from app.presentation.texts import (
    format_rating_personal,
    format_rating_group,
    format_organizers_list,
    format_organizer_profile,
    format_organizer_people,
)
from app.infrastructure.telegram.keyboards import link_preview_disabled

router = Router(name="reputation")


@router.message(Command("rating"))
async def rating_command(message: Message, repos: dict) -> None:
    service = ReputationService(repos["events"], repos["signups"], repos["event_attendance"])
    stats = await service.get_personal_stats(message.from_user.id)
    await message.answer(format_rating_personal(**stats))


@router.message(Command("grouprating"))
async def group_rating_command(message: Message, repos: dict) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Команда /grouprating доступна в группе.")
        return
    service = ReputationService(repos["events"], repos["signups"], repos["event_attendance"])
    stats = await service.get_group_stats(message.chat.id)
    await message.answer(format_rating_group(title=message.chat.title, **stats))


@router.message(Command("organizer"))
async def organizer_command(message: Message, repos: dict) -> None:
    if message.chat.type != "private":
        await message.answer("История организаторов доступна в личном чате с ботом.")
        return
    service = ReputationService(repos["events"], repos["signups"], repos["event_attendance"])
    total, rows = await service.list_organizers(page=0)
    if not rows:
        await message.answer("Пока никто не создавал встречи.")
        return
    await message.answer(
        format_organizers_list(total=total),
        reply_markup=organizers_keyboard(rows, page=0, total=total),
    )


@router.callback_query(F.data.startswith("org:list:"))
async def organizer_list_callback(query: CallbackQuery, repos: dict) -> None:
    await query.answer()
    if query.message.chat.type != "private":
        return
    page = max(0, int(query.data.split(":")[2]))
    service = ReputationService(repos["events"], repos["signups"], repos["event_attendance"])
    total, rows = await service.list_organizers(page=page)
    if not rows and page:
        page = 0
        total, rows = await service.list_organizers(page=page)
    await query.message.edit_text(
        format_organizers_list(total=total),
        reply_markup=organizers_keyboard(rows, page=page, total=total),
    )


@router.callback_query(F.data.startswith("org:profile:"))
async def organizer_profile_callback(query: CallbackQuery, repos: dict) -> None:
    await query.answer()
    if query.message.chat.type != "private":
        return
    parts = query.data.split(":")
    owner_id, page = int(parts[2]), max(0, int(parts[3]))
    service = ReputationService(repos["events"], repos["signups"], repos["event_attendance"])
    profile = await service.get_organizer_profile(owner_id)
    if profile is None:
        await query.message.edit_text(
            "История организатора не найдена.",
            reply_markup=organizers_keyboard([], page, 0),
        )
        return
    await query.message.edit_text(
        format_organizer_profile(**profile),
        parse_mode="HTML",
        reply_markup=organizer_profile_keyboard(owner_id, page),
        link_preview_options=link_preview_disabled(),
    )


@router.callback_query(F.data.startswith("org:people:"))
async def organizer_people_callback(query: CallbackQuery, repos: dict) -> None:
    await query.answer()
    if query.message.chat.type != "private":
        return
    parts = query.data.split(":")
    owner_id = int(parts[2])
    origin_page = max(0, int(parts[3]))
    people_page = max(0, int(parts[4]))
    service = ReputationService(repos["events"], repos["signups"], repos["event_attendance"])
    total, rows = await service.get_organizer_people(owner_id, people_page)
    offset = people_page * 15
    text = format_organizer_people(
        owner_id=owner_id, total=total, rows=list(rows), offset=offset
    )
    await query.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=organizer_people_keyboard(owner_id, origin_page, people_page, total),
        link_preview_options=link_preview_disabled(),
    )