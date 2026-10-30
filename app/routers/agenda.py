"""Афиша встреч: /vstrechi, /today, scope, dates, categories, page.

UX:
- `📅 Афиша встреч` (ReplyKeyboard) → `_show_scope`. Удаляет ВСЕ сообщения
  афиши (scope + карточки + участники), чтобы не спамить.
- `scope`, `pickdate`, `category`, `page` → `edit_text` (одно сообщение).
- `_show_event_page` — удаляет предыдущее, отправляет карточки.
"""

from __future__ import annotations

from datetime import date

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import categories_kb, dates_kb, pagination_kb, scope_menu
from app.labels import CATEGORY_LABELS
from app.services.agenda import AgendaService

logger = structlog.get_logger(__name__)
router = Router(name="agenda")


def _scope_token(scope: tuple[str, int | None]) -> str:
    return "public" if scope[0] == "public" else f"chat{scope[1]}"


def _scope_from_token(token: str) -> tuple[str, int | None] | None:
    if token == "public":
        return ("public", None)
    if token.startswith("chat"):
        try:
            return ("chat", int(token[4:]))
        except ValueError:
            return None
    return None


async def _delete_agenda_messages(message: Message, state: FSMContext) -> None:
    """Удалить все сообщения афиши (scope + карточки + пагинация)."""
    data = await state.get_data()
    ids = list(data.get("agenda_message_ids", []))
    if data.get("scope_message_id"):
        ids.append(data["scope_message_id"])
    for mid in ids:
        try:
            await message.bot.delete_message(message.chat.id, mid)
        except Exception:
            pass
    await state.update_data(agenda_message_ids=[], scope_message_id=None)


async def _track(state: FSMContext, message_id: int) -> None:
    """Запомнить id сообщения — чтобы удалить при переходе."""
    data = await state.get_data()
    ids = list(data.get("agenda_message_ids", []))
    ids.append(message_id)
    await state.update_data(agenda_message_ids=ids)


# ---------------------------------------------------------------------------
# /vstrechi, /today, текстовые триггеры
# ---------------------------------------------------------------------------


@router.message(Command("vstrechi"))
async def vstrechi(message: Message, state: FSMContext) -> None:
    await _show_scope(message, state)


@router.message(Command("today"))
async def today(message: Message, state: FSMContext) -> None:
    await _show_scope(message, state, forced_date=date.today())


@router.message(
    F.text.casefold().in_({"встречи", "ближайшие встречи", "📅 афиша встреч"})
)
async def text_vstrechi(message: Message, state: FSMContext) -> None:
    await _show_scope(message, state)


async def _show_scope(
    message: Message, state: FSMContext, forced_date: date | None = None
) -> None:
    await _delete_agenda_messages(message, state)

    chat_id = message.chat.id if message.chat.type in {"group", "supergroup"} else None
    text = "Выберите афишу:" if forced_date is None else "Выберите афишу на сегодня:"
    sent = await message.answer(text, reply_markup=scope_menu(chat_id))
    await state.update_data(scope_message_id=sent.message_id)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("scope:"))
async def cb_scope(query: CallbackQuery, session: AsyncSession) -> None:
    parts = query.data.split(":")
    if len(parts) < 2:
        await query.answer("Не удалось открыть афишу.", show_alert=True)
        return

    if parts[1] == "chat":
        if len(parts) < 3:
            await query.answer("Неверный scope.", show_alert=True)
            return
        try:
            source_id = int(parts[2])
        except ValueError:
            await query.answer("Неверный scope.", show_alert=True)
            return
        scope: tuple[str, int | None] = ("chat", source_id)
    elif parts[1] == "public":
        scope = ("public", None)
    else:
        await query.answer("Неверный scope.", show_alert=True)
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
        await query.answer("Не удалось определить дату.", show_alert=True)
        return

    scope = _scope_from_token(parts[1])
    if scope is None:
        await query.answer("Неверный scope.", show_alert=True)
        return

    try:
        day = date.fromisoformat(parts[2])
    except ValueError:
        await query.answer("Неверная дата.", show_alert=True)
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
async def cb_category(
    query: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Не удалось открыть категорию.", show_alert=True)
        return

    scope = _scope_from_token(parts[1])
    if scope is None:
        await query.answer("Неверный scope.", show_alert=True)
        return

    try:
        day = date.fromisoformat(parts[2])
        page_num = int(parts[4])
    except ValueError:
        await query.answer("Неверные параметры.", show_alert=True)
        return

    category = parts[3]
    await query.answer()
    await _show_event_page(query, session, scope, day, category, page_num, state)


@router.callback_query(F.data.startswith("page:"))
async def cb_page(
    query: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Не удалось открыть страницу.", show_alert=True)
        return

    scope = _scope_from_token(parts[1])
    if scope is None:
        await query.answer("Неверный scope.", show_alert=True)
        return

    try:
        day = date.fromisoformat(parts[2])
        page_num = int(parts[4])
    except ValueError:
        await query.answer("Неверные параметры.", show_alert=True)
        return

    category = parts[3]
    await query.answer()
    await _show_event_page(query, session, scope, day, category, page_num, state)


async def _show_event_page(
    query: CallbackQuery,
    session: AsyncSession,
    scope: tuple[str, int | None],
    day: date,
    category: str,
    page_num: int,
    state: FSMContext,
) -> None:
    from app.routers.events import send_event_card

    await _delete_agenda_messages(query.message, state)

    try:
        await query.message.delete()
    except Exception:
        pass

    service = AgendaService(session)
    events = await service.page(scope, day, category, page=page_num, per_page=10)

    if not events:
        sent = await query.message.answer(
            "В этой категории на выбранную дату встреч больше нет."
        )
        await _track(state, sent.message_id)
        return

    for event in events:
        sent = await send_event_card(
            query.message, session, event, private_details=True, viewer_id=None
        )
        await _track(state, sent.message_id)

    # Коммитим event_messages, иначе cleanup-worker их не увидит.
    try:
        await session.commit()
    except Exception:
        logger.exception("agenda_commit_failed")

    token = _scope_token(scope)
    has_next = len(events) == 10
    kb = pagination_kb(token, day.isoformat(), category, page_num, has_next)
    if kb is not None:
        sent_pag = await query.message.answer(
            f"Ещё встречи · {CATEGORY_LABELS.get(category, category)} · "
            f"страница {page_num + 1}:",
            reply_markup=kb,
        )
        await _track(state, sent_pag.message_id)