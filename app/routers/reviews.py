"""Отзывы на встречи: /review, /reviews, /delreview."""
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.filters.owner import IsOwner
from app.db.models import Event, Signup, EventReview
from app.db.repo.reviews import (
    create_review, get_user_reviews, get_event_reviews, delete_review as repo_delete_review,
)

router = Router(name="reviews")


@router.message(Command("review"))
async def cmd_review(message: Message, session: AsyncSession):
    """Оставить отзыв на встречу, на которую пользователь был записан."""
    if message.chat.type != "private":
        await message.answer("Команда /review доступна в личном чате с ботом.")
        return

    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Формат: /review ID_встречи 1-5 текст_отзыва")
        return

    try:
        event_id = int(parts[1])
        stars = int(parts[2])
        if not (1 <= stars <= 5):
            raise ValueError
    except ValueError:
        await message.answer("Укажите ID встречи и оценку от 1 до 5.")
        return

    review_text = " ".join(parts[3:])[:1000]

    # Проверяем, что пользователь был записан
    stmt = select(Signup.id).where(Signup.event_id == event_id, Signup.user_id == message.from_user.id)
    if not (await session.execute(stmt)).scalar_one_or_none():
        await message.answer("Вы не были записаны на эту встречу.")
        return

    # Получаем название встречи и ID организатора
    stmt = select(Event.title, Event.owner_id).where(Event.id == event_id)
    row = (await session.execute(stmt)).one_or_none()
    if not row:
        await message.answer("Встреча не найдена.")
        return

    await create_review(
        session=session,
        event_id=event_id,
        user_id=message.from_user.id,
        stars=stars,
        review=review_text,
        event_title=row.title,
        organizer_id=row.owner_id,
    )
    await message.answer(f"✅ Спасибо за отзыв! Оценка: {'⭐' * stars}")


@router.message(Command("reviews"))
async def cmd_reviews(message: Message, session: AsyncSession):
    """Мои последние отзывы."""
    if message.chat.type != "private":
        await message.answer("Команда /reviews доступна в личном чате с ботом.")
        return

    reviews = await get_user_reviews(session, message.from_user.id, limit=10)
    if not reviews:
        await message.answer("У вас пока нет отзывов.")
        return

    lines = ["📝 Ваши последние отзывы:"]
    for r in reviews:
        lines.append(f"\n«{r.event_title}» — {'⭐' * r.stars}")
        if r.review:
            lines.append(r.review[:200])

    await message.answer("\n".join(lines))


@router.message(Command("delreview"), IsOwner())
async def cmd_delreview(message: Message, session: AsyncSession):
    """Удалить отзыв (только владелец). Формат: /delreview ID_встречи ID_пользователя."""
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Формат: /delreview ID_встречи ID_пользователя")
        return

    try:
        event_id = int(parts[1])
        user_id = int(parts[2])
    except ValueError:
        await message.answer("Укажите числовые ID.")
        return

    deleted = await repo_delete_review(session, event_id, user_id)
    if deleted:
        await message.answer(f"✅ Отзыв удалён.")
    else:
        await message.answer(f"ℹ️ Отзыв не найден.")