"""Парсинг start-payload: join_123, cancel_123, detail_123, participants_123, create_-100.

Возвращает типизированный ``DeepLink`` или ``None``, если payload не распознан.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Action = Literal[
    "join", "cancel", "detail", "participants", "create", "none",
]


@dataclass(frozen=True)
class DeepLink:
    action: Action
    event_id: int | None = None
    chat_id: int | None = None


_PREFIXES: tuple[tuple[str, Action], ...] = (
    ("join_", "join"),
    ("cancel_", "cancel"),
    ("detail_", "detail"),
    ("participants_", "participants"),
)


def parse_start_payload(payload: str | None) -> DeepLink:
    """Разобрать payload после ``/start``.

    :param payload: строка после ``/start`` (может быть пустой/None).
    :return: ``DeepLink``; ``action="none"`` — payload не распознан.
    """
    if not payload:
        return DeepLink(action="none")

    for prefix, action in _PREFIXES:
        if payload.startswith(prefix):
            try:
                event_id = int(payload[len(prefix):])
            except ValueError:
                return DeepLink(action="none")
            return DeepLink(action=action, event_id=event_id)

    if payload.startswith("create_"):
        try:
            chat_id = int(payload[len("create_"):])
        except ValueError:
            return DeepLink(action="none")
        return DeepLink(action="create", chat_id=chat_id)

    return DeepLink(action="none")