# app/infrastructure/telegram/routers/participants.py
from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from html import escape

from app.application.services.participant_service import ParticipantService
from app.application.services.event_service import EventService
from app.application.services.event_message_service import EventMessageService
from app.application.services.security_service import SecurityService
from app.domain.exceptions import DomainError
from app.infrastructure.telegram.keyboards import (
    event_keyboard,
    manage_people_keyboard,
    delete_ask_keyboard,
    private_chat_keyboard,
    link_preview_disabled,
)
from app.presentation.texts import (
    event_card_text,
    format_join_success,
    format_cancel_success,
    format_participants_chunks,
    format_manage_people,
    event_origin_label,
)

router = Router(name="participants")


@router.callback_query(F.data.startswith("join:"))
async def join_callback(query: CallbackQuery, repos: dict, security: SecurityService, bot: Bot) -> None:
    event_id = int(query.data.split(":")[1])
    service = ParticipantService(
        repos["signups"],
        repos["participants"],
        repos["events"],
        repos["event_exclusions"],
        repos["event_messages"],
        security,
        bot,
    )
    try:
        result = await service.join_event(
            event_id,
            query.from_user,
            current_chat_type=query.message.chat.type,
            current_chat_id=query.message.chat.id,
        )
        await query.message.answer(result.message)
        origin = event_origin_label(
            result.event, query.message.chat.type, query.message.chat.id
        )
        success_text = format_join_success(
            result.event, query.from_user.id, query.from_user.full_name or str(query.from_user.id),
            result.available, origin,
        )
        await query.message.answer(success_text, parse_mode="HTML", link_preview_options=link_preview_disabled())
        await EventMessageService(repos["event_messages"], repos["events"], bot).refresh_event_messages(event_id)
        await service.notify_source_group(result.event, query.from_user, result.available, joined=True)
    except DomainError as exc:
        await query.message.answer(exc.message)


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_callback(query: CallbackQuery, repos: dict, security: SecurityService, bot: Bot) -> None:
    event_id = int(query.data.split(":")[1])
    service = ParticipantService(
        repos["signups"],
        repos["participants"],
        repos["events"],
        repos["event_exclusions"],
        repos["event_messages"],
        security,
        bot,
    )
    try:
        result = await service.cancel_signup(event_id, query.from_user)
        await query.message.answer(result.message)
        origin = event_origin_label(
            result.event, query.message.chat.type, query.message.chat.id
        )
        success_text = format_cancel_success(
            result.event, query.from_user.id, query.from_user.full_name or str(query.from_user.id),
            result.available, origin,
        )
        await query.message.answer(success_text, parse_mode="HTML", link_preview_options=link_preview_disabled())
        await EventMessageService(repos["event_messages"], repos["events"], bot).refresh_event_messages(event_id)
        await service.notify_source_group(result.event, query.from_user, result.available, joined=False)
    except DomainError as exc:
        await query.message.answer(exc.message)


@router.callback_query(F.data.startswith("participants:"))
async def participants_callback(query: CallbackQuery, repos: dict, security: SecurityService, bot: Bot) -> None:
    event_id = int(query.data.split(":")[1])
    result = await repos["events"].get_with_booked_count(event_id)
    if result is None:
        await query.message.answer("Встреча не найдена.")
        return
    event, booked = result
    if not await security.check_event_access(
        event, query.from_user.id, query.message.chat.type, query.message.chat.id
    ):
        await query.message.answer("Список доступен только участникам чата-организатора.")
        return
    signups = await repos["signups"].list_for_event(event_id)
    names = [
        (s.telegram_name or "Имя не указано").replace("\r", " ").replace("\n", " ")
        for s in signups
    ]
    heading = (
        f"👤 {('@' + query.from_user.username) if query.from_user.username else query.from_user.full_name}, запросил(а) список.\n"
        f"👥 Участники встречи «{event.title}»\n"
        f"Записано: {len(names)}/{event.capacity}"
    )
    chunks = format_participants_chunks(heading, names)
    for chunk in chunks:
        await query.message.answer(chunk)


@router.callback_query(F.data.startswith("full:"))
async def full_callback(query: CallbackQuery) -> None:
    await query.answer("К сожалению, свободных мест уже нет.", show_alert=True)


@router.callback_query(F.data.startswith("deleteask:"))
async def delete_ask_callback(query: CallbackQuery, repos: dict) -> None:
    event_id = int(query.data.split(":")[1])
    event = await repos["events"].get_by_id(event_id)
    if event is None or (event.owner_id != query.from_user.id and not SecurityService.is_platform_owner(query.from_user.id)):
        await query.message.answer("Встреча не найдена или у вас нет прав.")
        return
    await query.message.answer(
        f"Вы уверены, что хотите удалить встречу «{event.title}»?",
        reply_markup=delete_ask_keyboard(event_id),
    )


@router.callback_query(F.data.startswith("deleteyes:"))
async def delete_yes_callback(query: CallbackQuery, repos: dict, bot: Bot) -> None:
    event_id = int(query.data.split(":")[1])
    service = EventService(repos["events"], repos["signups"], repos["event_exclusions"])
    try:
        await service.delete_event(
            event_id, query.from_user.id, is_platform_owner=SecurityService.is_platform_owner(query.from_user.id)
        )
        await query.message.answer("Встреча удалена.")
        await EventMessageService(repos["event_messages"], repos["events"], bot).refresh_event_messages(event_id)
    except DomainError as exc:
        await query.message.answer(exc.message)


@router.callback_query(F.data.startswith("deleteno:"))
async def delete_no_callback(query: CallbackQuery) -> None:
    await query.message.answer("Удаление отменено.")


@router.callback_query(F.data.startswith("managepeople:"))
async def manage_people_callback(query: CallbackQuery, repos: dict) -> None:
    parts = query.data.split(":")
    event_id, page = int(parts[1]), int(parts[2])
    event = await repos["events"].get_with_count(event_id)
    if event is None or (event.owner_id != query.from_user.id and not SecurityService.is_platform_owner(query.from_user.id)):
        await query.message.answer("Встреча не найдена или у вас нет прав.")
        return
    active = await repos["signups"].list_for_event(event_id)
    excluded = await repos["event_exclusions"].list_by_event(event_id)
    page_size = 8
    pages = max(1, (len(active) + len(excluded) + page_size - 1) // page_size)
    page = min(max(0, page), pages - 1)
    text = format_manage_people(event, active, excluded, page, pages)
    keyboard = manage_people_keyboard(event_id, active, excluded, page, pages)
    await query.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("kickask:"))
async def kick_ask_callback(query: CallbackQuery, repos: dict, bot: Bot) -> None:
    parts = query.data.split(":")
    event_id, user_id = int(parts[1]), int(parts[2])
    event = await repos["events"].get_by_id(event_id)
    if event is None or (event.owner_id != query.from_user.id and not SecurityService.is_platform_owner(query.from_user.id)):
        await query.message.answer("У вас нет прав.")
        return
    service = ParticipantService(
        repos["signups"], repos["participants"], repos["events"], repos["event_exclusions"],
        repos["event_messages"], None, bot,
    )
    await service.exclude_user(event_id, user_id, query.from_user.id)
    await query.answer("Пользователь исключён.", show_alert=True)


@router.callback_query(F.data.startswith("restoreask:"))
async def restore_ask_callback(query: CallbackQuery, repos: dict, bot: Bot) -> None:
    parts = query.data.split(":")
    event_id, user_id = int(parts[1]), int(parts[2])
    event = await repos["events"].get_by_id(event_id)
    if event is None or (event.owner_id != query.from_user.id and not SecurityService.is_platform_owner(query.from_user.id)):
        await query.message.answer("У вас нет прав.")
        return
    service = ParticipantService(
        repos["signups"], repos["participants"], repos["events"], repos["event_exclusions"],
        repos["event_messages"], None, bot,
    )
    await service.restore_user(event_id, user_id)
    await query.answer("Доступ восстановлен.", show_alert=True)