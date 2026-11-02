"""Роутер для афиши встреч (/vstrechi)."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.db.models import Event
from app.config import settings
from app.services.events import get_event_with_count, event_card_text
from app.keyboards.events import event_keyboard

router = Router(name="agenda")

@router.message(Command("vstrechi"))
@router.message(F.text == "📅 Афиша встреч")
async def cmd_agenda(message: Message, session: AsyncSession):
    """Показывает ближайшие встречи (публичные + встречи пользователя)."""
    now_dt = datetime.now(settings.tzinfo)
    
    # Запрашиваем публичные встречи и встречи пользователя на ближайшие 14 дней
    stmt = (
        select(Event)
        .where(
            Event.starts_at >= now_dt,
            Event.starts_at <= now_dt + timedelta(days=14),
            (Event.visibility == "public") | (Event.owner_id == message.from_user.id)
        )
        .order_by(Event.starts_at.asc())
        .limit(10)
    )
    result = await session.execute(stmt)
    events = result.scalars().all()

    if not events:
        await message.answer(
            "📅 На ближайшие 14 дней встреч пока нет.\n"
            "Вы можете создать свою встречу с помощью кнопки ➕ Создать встречу."
        )
        return

    await message.answer(f"📅 Афиша встреч (ближайшие 14 дней):")
    
    for event_model in events:
        event = await get_event_with_count(session, event_model.id)
        text = event_card_text(event)
        
        if event["photo_file_id"]:
            await message.answer_photo(
                photo=event["photo_file_id"],
                caption=text,
                reply_markup=event_keyboard(event, message.from_user.id)
            )
        else:
            await message.answer(
                text,
                reply_markup=event_keyboard(event, message.from_user.id)
            )

# Заглушка для будущих фильтров по дате/категории (будет расширена в Шаге 5)
@router.callback_query(F.data.startswith("agenda:filter:"))
async def cb_agenda_filter(callback: CallbackQuery, session: AsyncSession):
    await callback.answer("Фильтры в разработке (Шаг 5)", show_alert=True)