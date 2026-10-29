"""Сборка корневого роутера: порядок приоритета.

Порядок важен: FSM-роутеры (create, mine) — раньше общих callback/message,
чтобы /cancel и состояния не перехватывались.
"""

from __future__ import annotations

from aiogram import Router

from app.routers.admin import router as admin_router
from app.routers.agenda import router as agenda_router
from app.routers.create import router as create_router
from app.routers.events import router as events_router
from app.routers.fallback import router as fallback_router
from app.routers.group import router as group_router
from app.routers.mine import router as mine_router
from app.routers.start import router as start_router


def assemble_root_router() -> Router:
    """Собрать все роутеры в правильном порядке.

    - start: deep-links и /start — должны матчиться раньше.
    - create, mine: FSM-роутеры (ловят свои состояния).
    - agenda, events: обычные callback/message.
    - group: групповые триггеры.
    - admin: /stats (только owner_id).
    - fallback: /help и «всё остальное» — последним.
    """
    root = Router(name="root")
    root.include_router(start_router)
    root.include_router(create_router)
    root.include_router(mine_router)
    root.include_router(agenda_router)
    root.include_router(events_router)
    root.include_router(group_router)
    root.include_router(admin_router)
    root.include_router(fallback_router)
    return root