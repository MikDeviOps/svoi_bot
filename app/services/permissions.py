"""Проверки прав доступа к встречам.

``can_access_event`` синхронно проверяет public/chat по кэшу чатов,
а для ``chat`` — членство пользователя через ``bot.get_chat_member``.

Чтобы не тащить ``aiogram`` в сервисы, ``bot`` передаётся как Protocol
с методом ``get_chat_member``. В тестах — фейк, в проде — настоящий
``aiogram.Bot``.
"""

from __future__ import annotations

from typing import Protocol

from app.db import Event
from app.errors import Forbidden


class ChatMemberProtocol(Protocol):
    status: str
    is_member: bool | None


class BotProtocol(Protocol):
    async def get_chat_member(
        self, chat_id: int, user_id: int
    ) -> ChatMemberProtocol: ...


async def is_source_chat_member(bot: BotProtocol, chat_id: int, user_id: int) -> bool:
    """True, если пользователь — член чата.

    Считаем членом при статусах ``creator``/``administrator``/``member``,
    а также ``restricted`` с ``is_member=True``.

    ``bot.get_chat_member`` может:
    - вернуть ``None`` (фейки в тестах);
    - кинуть исключение (пользователя нет в чате, бот не в чате, сеть).
    В обоих случаях возвращаем ``False``.
    """
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    except Exception:
        return False

    if member is None:
        return False

    status = getattr(member.status, "value", member.status)
    if status in {"creator", "administrator", "member"}:
        return True
    if status == "restricted" and getattr(member, "is_member", False):
        return True
    return False


async def is_group_admin(bot: BotProtocol, chat_id: int, user_id: int) -> bool:
    """True, если ``user_id`` — админ/создатель ``chat_id``.

    Используется при создании встречи от имени группы (``/create``).
    """
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    except Exception:
        return False

    if member is None:
        return False

    status = getattr(member.status, "value", member.status)
    return status in {"creator", "administrator", "owner"}


async def can_access_event(
    event: Event,
    *,
    chat_id: int | None,
    chat_type: str | None,
    user_id: int,
    bot: BotProtocol,
) -> bool:
    """True, если пользователь может видеть/записаться на встречу.

    - ``visibility='public'`` — доступно всем.
    - ``visibility='chat'``:
        * текущий чат == ``source_chat_id`` → доступно;
        * иначе — проверка членства в ``source_chat_id`` через ``bot``.
    """
    if event.visibility == "public":
        return True

    source_chat_id = event.source_chat_id
    if source_chat_id is None:
        return False

    if chat_id == source_chat_id and chat_type in {"group", "supergroup"}:
        return True

    return await is_source_chat_member(bot, source_chat_id, user_id)


def ensure_owner(event: Event, actor_id: int) -> None:
    """Кинуть ``Forbidden``, если ``actor_id`` — не владелец встречи."""
    if event.owner_id != actor_id:
        raise Forbidden("Действие доступно только организатору встречи.")