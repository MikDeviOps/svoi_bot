"""/start + deep-links.

- ``/start`` без payload → приветствие + главное меню.
- ``/start join_123`` → вызов ``events.handle_join`` (Шаг 6, заглушка).
- ``/start cancel_123`` → аналогично.
- ``/start create_-100...`` → FSM создания (Шаг 6, заглушка).
- Битые payload → «Ссылка недействительна».
"""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import main_menu
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
) -> None:
    """Deep-link из кнопки «Открыть личный чат» или шаринга."""
    link: DeepLink = parse_start_payload(command.args)
    logger.info("start_deeplink", action=link.action, event_id=link.event_id, chat_id=link.chat_id)

    if link.action == "none":
        if command.args:
            await message.answer("Ссылка недействительна.")
            return
        await _greet(message, is_private=message.chat.type == "private")
        return

    if link.action in {"join", "cancel", "participants", "detail"}:
        # Шаг 6: вызов хендлеров events. Пока — заглушка.
        await message.answer(
            f"🔗 Действие: <b>{link.action}</b>, встреча №{link.event_id}.\n"
            "Обработчик появится в Шаге 6."
        )
        return

    if link.action == "create":
        # Шаг 6: запуск FSM создания. Пока — заглушка.
        await message.answer(
            f"🔗 Создание встречи от группы <code>{link.chat_id}</code>.\n"
            "FSM появится в Шаге 6."
        )
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