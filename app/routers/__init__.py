"""Сборка корневого роутера: порядок приоритета.

Порядок важен: FSM-роутеры (create, edit) — раньше общих callback/message.
"""

from __future__ import annotations

from aiogram import Router

from app.routers.agenda import router as agenda_router
from app.routers.events import router as events_router
from app.routers.fallback import router as fallback_router
from app.routers.start import router as start_router


def assemble_root_router() -> Router:
    """Собрать все роутеры в правильном порядке.

    Шаг 6 — start, agenda, events, fallback. На Шагах 7–8 добавятся
    create (FSM), edit, mine, group.
    """
    root = Router(name="root")
    root.include_router(start_router)
    root.include_router(agenda_router)
    root.include_router(events_router)
    root.include_router(fallback_router)
    return root