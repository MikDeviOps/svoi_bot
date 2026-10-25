"""Сборка корневого роутера: порядок приоритета.

Порядок важен: FSM-роутеры (create, edit) — раньше, чем общие
callback/message, чтобы не перехватить чужие состояния.
"""

from __future__ import annotations

from aiogram import Router

from app.routers.fallback import router as fallback_router
from app.routers.start import router as start_router


def assemble_root_router() -> Router:
    """Собрать все роутеры в правильном порядке.

    Шаг 5 — только start и fallback. На следующих шагах добавятся
    create, edit, events, agenda, mine, group.
    """
    root = Router(name="root")
    root.include_router(start_router)
    root.include_router(fallback_router)
    return root