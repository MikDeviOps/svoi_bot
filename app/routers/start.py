"""/start + deep-links.

- ``/start`` без payload → приветствие + главное меню.
- ``/start join_123`` → запись на встречу (в личке).
- ``/start cancel_123`` → отмена записи.
- ``/start participants_123`` → список участников.
- ``/start detail_123`` → карточка встречи.
- ``/start create_-100...`` → FSM создания.
- Битые payload → «Ссылка недействительна».
"""

from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import event_kb, main_menu
from app.services.deeplinks import DeepLink, parse_start_payload

logger = structlog.get_logger(__name__)
router = Router(name="start")


GREETING = (
    "Привет! Я <b>СВОИ</b> — афиша встреч Москвы.\n\n"
    "Команды:\n"
    "/vstrechi — афиша встреч\n"
    "/today — встречи на сегодня\n"
    "/create — создать встречу\n"
    "/mine — мои встречи\n"
    "/help — помощь"
)


@router.message(CommandStart(deep_link=True))
async def start_with_payload(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user,
    state: FSMContext,
) -> None:
    """Deep-link из кнопки «Открыть личный чат» или шаринга."""
    link: DeepLink = parse_start_payload(command.args)
    logger.info(
        "start_deeplink",
        action=link.action,
        event_id=link.event_id,
        chat_id=link.chat_id,
    )

    if link.action == "none":
        if command.args:
            await message.answer("Ссылка недействительна.")
            return
        await _greet(message, is_private=message.chat.type == "private")
        return

    if link.action in {"join", "cancel", "participants", "detail"}:
        await _handle_event_deeplink(message, session, link)
        return

    if link.action == "create":
        from app.routers.create import start_create_from_group
        await start_create_from_group(message, link.chat_id, session, state)
        return

    await message.answer("Ссылка недействительна.")


@router.message(CommandStart())
async def start(message: Message) -> None:
    """``/start`` без payload."""
    await _greet(message, is_private=message.chat.type == "private")


async def _greet(message: Message, *, is_private: bool) -> None:
    await message.answer(
        GREETING,
        reply_markup=main_menu() if is_private else None,
    )


# ---------------------------------------------------------------------------
# Deep-links: join / cancel / participants / detail
# ---------------------------------------------------------------------------


class _UserView:
    """Обёртка над ``aiogram.types.User`` для ``SignupService``.

    ``SignupService.join`` ожидает объект с ``tg_id``/``username``/``full_name``.
    В хендлерах это ORM ``User`` (из ``UserUpsertMiddleware``), а в deep-link
    приходит ``message.from_user`` — у него ``id``, не ``tg_id``. Оборачиваем.
    """

    __slots__ = ("tg_id", "username", "full_name")

    def __init__(self, tg_user) -> None:
        self.tg_id = tg_user.id
        self.username = tg_user.username or ""
        self.full_name = tg_user.full_name or ""


async def _handle_event_deeplink(
    message: Message,
    session: AsyncSession,
    link: DeepLink,
) -> None:
    """Обработка deep-link в личке: join/cancel/participants/detail.

    Действует от имени пользователя, открывшего ссылку.
    """
    from app.db import Event, User
    from app.errors import DomainError
    from app.routers.events import _save_event_message
    from app.services.events import _count_booked
    from app.services.notifications import enqueue_refresh, render_card
    from app.services.permissions import can_access_event
    from app.services.signups import SignupService

    event = await session.get(Event, link.event_id)
    if event is None or event.deleted_at is not None:
        await message.answer("Встреча не найдена.")
        return

    if not await can_access_event(
        event,
        chat_id=None,
        chat_type=message.chat.type,
        user_id=message.from_user.id,
        bot=message.bot,
    ):
        await message.answer(
            "Эта встреча доступна только участникам чата-организатора."
        )
        return

    service = SignupService(session)

    if link.action == "join":
        try:
            result = await service.join(link.event_id, _UserView(message.from_user))
        except DomainError as exc:
            await message.answer(exc.user_message)
            return
        if result.joined:
            await enqueue_refresh(link.event_id, session, message.bot)
            await message.answer(
                f"✅ Вы записаны на встречу «{event.title}».\n"
                f"👥 Свободно мест: {result.available}."
            )
        else:
            await message.answer(result.reason)
        return

    if link.action == "cancel":
        try:
            result = await service.cancel(link.event_id, message.from_user.id)
        except DomainError as exc:
            await message.answer(exc.user_message)
            return
        await enqueue_refresh(link.event_id, session, message.bot)
        await message.answer(
            f"❌ Запись на встречу «{event.title}» отменена.\n"
            f"👥 Свободно мест: {result.available}."
        )
        return

    if link.action == "participants":
        participants = await service.list_participants(link.event_id)
        if not participants:
            await message.answer(
                f"👥 Участники встречи «{event.title}»\n"
                f"Записано: 0/{event.capacity}\n"
                "Пока никто не записался."
            )
            return
        names = "\n".join(
            f"• {p.telegram_name or p.user_id}" for p in participants
        )
        await message.answer(
            f"👥 Участники встречи «{event.title}»\n"
            f"Записано: {len(participants)}/{event.capacity}\n{names}"
        )
        return

    if link.action == "detail":
        booked = await _count_booked(session, link.event_id)
        owner = await session.get(User, event.owner_id)
        text = render_card(
            event,
            booked,
            owner_name=owner.full_name if owner else "",
            owner_username=owner.username if owner else "",
            private_details=True,
        )
        kb = event_kb(event, booked, viewer_id=message.from_user.id)
        sent = await message.answer(text, reply_markup=kb, parse_mode="HTML")
        await _save_event_message(session, sent, link.event_id)
        return