# app/application/services/security_service.py
from __future__ import annotations

from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbidden, TelegramAPIError

from app.application.ports.repositories import SecurityRepository
from app.config import settings
from app.domain.exceptions import (
    GroupBlockedError,
    GroupNotApprovedError,
    NotGroupAdminError,
    GroupTooSmallError,
    UserBlockedError,
    AccessDeniedError,
)
from app.infrastructure.redis.keys import RedisKeys


class CachePort(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, *, ttl: int) -> None: ...


SUPPORT_INVITE_FALLBACK = "https://t.me/+nucXNSA9t5QzZmEy"


class SecurityService:
    def __init__(
        self,
        security_repo: SecurityRepository,
        cache: CachePort | None,
        bot: Bot,
    ) -> None:
        self._security = security_repo
        self._cache = cache
        self._bot = bot

    @staticmethod
    def is_platform_owner(user_id: int) -> bool:
        return user_id in settings.OWNERS

    async def check_user_blocked(self, user_id: int, username: str | None = None) -> None:
        if await self._security.is_user_blocked(user_id):
            raise UserBlockedError()
        if username and not self.is_platform_owner(user_id):
            resolved = await self._security.resolve_pending_username_ban(
                user_id, username.lstrip("@").lower()
            )
            if resolved:
                raise UserBlockedError()

    async def check_group_blocked(self, chat_id: int) -> None:
        if await self._security.is_group_blocked(chat_id):
            raise GroupBlockedError()

    async def check_group_approved(self, chat_id: int) -> None:
        status = await self._security.get_group_application_status(chat_id)
        if status != "approved":
            raise GroupNotApprovedError()

    async def check_is_group_admin(self, chat_id: int, user_id: int) -> None:
        try:
            member = await self._bot.get_chat_member(chat_id, user_id)
            if member.status not in {"creator", "administrator"}:
                raise NotGroupAdminError()
        except (TelegramBadRequest, TelegramForbidden):
            raise NotGroupAdminError()

    async def check_group_size(self, chat_id: int) -> None:
        cache_key = RedisKeys.group_size_cache(chat_id)
        cached = await self._cache.get(cache_key) if self._cache else None
        if cached is not None:
            count = int(cached)
        else:
            try:
                count = await self._bot.get_chat_member_count(chat_id)
                if self._cache:
                    await self._cache.set(cache_key, str(count), ttl=300)
            except (TelegramBadRequest, TelegramForbidden):
                raise GroupTooSmallError(0, settings.MIN_GROUP_SIZE)
        if count < settings.MIN_GROUP_SIZE:
            raise GroupTooSmallError(count, settings.MIN_GROUP_SIZE)

    async def check_creation_permission(self, group_id: int, user_id: int) -> None:
        await self.check_user_blocked(user_id)
        await self.check_group_approved(group_id)
        await self.check_group_blocked(group_id)
        await self.check_is_group_admin(group_id, user_id)
        await self.check_group_size(group_id)

    async def check_support_membership(self, user_id: int) -> bool:
        cache_key = RedisKeys.chat_member_cache(settings.SUPPORT_CHAT_ID, user_id)
        cached = await self._cache.get(cache_key) if self._cache else None
        if cached is not None:
            return cached == "1"
        try:
            member = await self._bot.get_chat_member(settings.SUPPORT_CHAT_ID, user_id)
            is_member = member.status in {"creator", "administrator", "member"} or (
                member.status == "restricted" and bool(getattr(member, "is_member", False))
            )
            if self._cache:
                await self._cache.set(cache_key, "1" if is_member else "0", ttl=300)
            return is_member
        except (TelegramBadRequest, TelegramForbidden):
            return False

    async def check_event_access(
        self, event, user_id: int, current_chat_type: str | None, current_chat_id: int | None
    ) -> bool:
        """Возвращает True, если пользователь может видеть встречу."""
        try:
            await self.check_user_blocked(user_id)
        except UserBlockedError:
            return False
        if event.source_chat_id is not None:
            try:
                await self.check_group_blocked(event.source_chat_id)
            except GroupBlockedError:
                return False
        if event.visibility == "chat" and event.source_chat_id is not None:
            try:
                member = await self._bot.get_chat_member(event.source_chat_id, user_id)
                if member.status not in {"creator", "administrator", "member"} and not (
                    member.status == "restricted" and bool(getattr(member, "is_member", False))
                ):
                    return False
            except (TelegramBadRequest, TelegramForbidden):
                return False
        return True

    async def get_support_invite_url(self) -> str:
        try:
            chat = await self._bot.get_chat(settings.SUPPORT_CHAT_ID)
            if getattr(chat, "username", None):
                return f"https://t.me/{chat.username}"
            if getattr(chat, "invite_link", None):
                return chat.invite_link
        except TelegramAPIError:
            pass
        return SUPPORT_INVITE_FALLBACK