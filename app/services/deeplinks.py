"""Парсинг start-payload → typed action.

Deep-link, который бот получает в ``/start <payload>``:
- ``join_<id>``         → записаться на встречу
- ``cancel_<id>``       → отменить запись
- ``participants_<id>`` → список участников
- ``detail_<id>``       → карточка встречи (как ``event_``, но без фото)
- ``event_<id>``        → карточка встречи с фото (для group_event_url_kb)
- ``create_<chat_id>``  → продолжить создание встречи в личке
- ``apply_<chat_id>``   → заявка на регистрацию группы

Модуль не знает про aiogram и БД — только разбирает строку.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal[
    "join",
    "cancel",
    "participants",
    "detail",
    "event",
    "create",
    "apply",
]

# Порядок важен: `event_` должен идти до любого гипотетического `e_`,
# но у нас префиксы не пересекаются — порядок не критичен.
_PREFIXES: dict[str, Action] = {
    "join_": "join",
    "cancel_": "cancel",
    "participants_": "participants",
    "detail_": "detail",
    "event_": "event",
    "create_": "create",
    "apply_": "apply",
}


@dataclass(frozen=True)
class Deeplink:
    action: Action
    target_id: int


def parse(payload: str) -> Deeplink | None:
    """Разобрать payload. ``None`` — если payload не наш или битый."""
    if not payload:
        return None
    for prefix, action in _PREFIXES.items():
        if payload.startswith(prefix):
            try:
                target = int(payload[len(prefix):])
            except ValueError:
                return None
            # create_<chat_id> — только групповой чат (отрицательный id).
            if action == "create" and target >= 0:
                return None
            # apply_<chat_id> — тоже только группа.
            if action == "apply" and target >= 0:
                return None
            return Deeplink(action=action, target_id=target)
    return None