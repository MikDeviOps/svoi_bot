"""Утилиты для работы со временем (MSK)."""
from datetime import datetime
from app.config import settings

def now_msk() -> datetime:
    """Возвращает текущее время в часовом поясе, указанном в настройках (по умолчанию Europe/Moscow)."""
    return datetime.now(settings.tzinfo)