"""Афиша встреч: /vstrechi, /today, scope, dates, categories, page.

Inline-кнопки: выбор scope, даты, категории, пагинация.
Карточки рендерятся в ``events.show_event_card``.
"""

from __future__ import annotations

from datetime import date, datetime

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import categories_kb, dates_kb, pagination_kb, scope_menu
from app.services.agenda import AgendaService

logger = structlog.get_logger(__name__)
router = Router(name="agenda")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scope_token(scope: tuple[str, int | None]) -> str:
    if scope[0] == "public":
        return "public"
    return f"chat{scope[1]}"


def _scope_from_token(token: str) -> tuple[str, int | None] | None:
    if token == "public":
        return ("public", None)
    if token.startswith("chat"):
        try:
            return ("chat", int(token[4:]))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# /vstrechi, /today
# ---------------------------------------------------------------------------


@router.message(Command("vstrechi"))
async def vstrechi(message: Message) -> None:
    await _show_scope(message)


@router.message(Command("today"))
async def today(message: Message) -> None:
    await _show_scope(message, forced_date=date.today())


@router.message(F.text.casefold().in_({"встречи", "ближайшие встречи", "📅 афиша встреч"}))
async def text_vstrechi(message: Message) -> None:
    await _show_scope(message)


async def _show_scope(message: Message, forced_date: date | None = None) -> None:
    """Показать выбор scope (для групп — и чат, и общая; для лички — только общая)."""
    chat_id = message.chat.id if message.chat.type in {"group", "supergroup"} else None
    text = "Выберите афишу:" if forced_date is None else "Выберите афишу на сегодня:"
    await message.answer(text, reply_markup=scope_menu(chat_id))


# ---------------------------------------------------------------------------
# Callbacks: scope, pickdate, category, page
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("scope:"))
async def cb_scope(query: CallbackQuery, session: AsyncSession) -> None:
    parts = query.data.split(":")
    if len(parts) < 2:
        await query.answer("Не удалось открыть афишу.")
        return

    if parts[1] == "chat":
        if len(parts) < 3:
            await query.answer("Неверный scope.")
            return
        try:
            source_id = int(parts[2])
        except ValueError:
            await query.answer("Неверный scope.")
            return
        scope: tuple[str, int | None] = ("chat", source_id)
    elif parts[1] == "public":
        scope = ("public", None)
    else:
        await query.answer("Неверный scope.")
        return

    await query.answer()
    service = AgendaService(session)
    page = await service.dates(scope)

    if not page.dates:
        await query.message.edit_text("Ближайших встреч в этой афише пока нет.")
        return

    token = _scope_token(scope)
    iso_dates = [d.isoformat() for d in page.dates]
    await query.message.edit_text(
        "Ближайшие даты с запланированными встречами:",
        reply_markup=dates_kb(token, iso_dates),
    )


@router.callback_query(F.data.startswith("pickdate:"))
async def cb_pickdate(query: CallbackQuery, session: AsyncSession) -> None:
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.answer("Не удалось определить дату.")
        return

    scope = _scope_from_token(parts[1])
    if scope is None:
        await query.answer("Неверный scope.")
        return

    try:
        day = date.fromisoformat(parts[2])
    except ValueError:
        await query.answer("Неверная дата.")
        return

    await query.answer()
    service = AgendaService(session)
    page = await service.categories(scope, day)

    if not page.categories:
        await query.message.edit_text("На эту дату встреч больше нет.")
        return

    token = _scope_token(scope)
    await query.message.edit_text(
        f"Выберите категорию · {day.strftime('%d.%m.%Y')}:",
        reply_markup=categories_kb(token, day.isoformat(), page.categories),
    )


@router.callback_query(F.data.startswith("category:"))
async def cb_category(query: CallbackQuery, session: AsyncSession) -> None:
    # category:<token>:<date>:<slug>:<page>
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Не удалось открыть категорию.")
        return

    scope = _scope_from_token(parts[1])
    if scope is None:
        await query.answer("Неверный scope.")
        return

    try:
        day = date.fromisoformat(parts[2])
        page_num = int(parts[4])
    except ValueError:
        await query.answer("Неверные параметры.")
        return

    category = parts[3]
    await query.answer()
    await _show_event_page(query.message, session, scope, day, category, page_num)


@router.callback_query(F.data.startswith("page:"))
async def cb_page(query: CallbackQuery, session: AsyncSession) -> None:
    # page:<token>:<date>:<slug>:<page>
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Не удалось открыть страницу.")
        return

    scope = _scope_from_token(parts[1])
    if scope is None:
        await query.answer("Неверный scope.")
        return

    try:
        day = date.fromisoformat(parts[2])
        page_num = int(parts[4])
    except ValueError:
        await query.answer("Неверные параметры.")
        return

    category = parts[3]
    await query.answer()
    await _show_event_page(query.message, session, scope, day, category, page_num)


async def _show_event_page(
    message,
    session: AsyncSession,
    scope: tuple[str, int | None],
    day: date,
    category: str,
    page_num: int,
) -> None:
    """Показать карточки событий категории на странице ``page_num``."""
    from app.routers.events import send_event_card  # локальный импорт — избегаем цикла
    from app.services.notifications import CATEGORY_LABELS

    service = AgendaService(session)
    events = await service.page(scope, day, category, page=page_num, per_page=10)

    if not events:
        await message.answer("В этой категории на выбранную дату встреч больше нет.")
        return

    for event in events:
        await send_event_card(message, session, event, private_details=True)

    # Пагинация: если есть 10 — возможно, есть ещё
    token = _scope_token(scope)
    has_next = len(events) == 10
    kb = pagination_kb(token, day.isoformat(), category, page_num, has_next)
    if kb is not None:
        await message.answer(
            f"Ещё встречи · {CATEGORY_LABELS.get(category, category)} · "
            f"страница {page_num + 1}:",
            reply_markup=kb,
        )


# Legacy callback: scope-menu (если кто-то вызывает)
@router.callback_query(F.data == "scope-menu")
async def cb_scope_menu(query: CallbackQuery) -> None:
    await query.answer()
    chat_id = query.message.chat.id if query.message.chat.type in {"group", "supergroup"} else None
    await query.message.answer("Выберите афишу:", reply_markup=scope_menu(chat_id))