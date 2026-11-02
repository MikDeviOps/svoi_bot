"""Фильтр для проверки прав владельца платформы."""
from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject
from app.config import settings

class IsOwner(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        if not user:
            return False
        return user.id in settings.owners