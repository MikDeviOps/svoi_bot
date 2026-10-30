# app/infrastructure/telegram/routers/reviews.py
from __future__ import annotations

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command

from app.application.services.review_service import ReviewService
from app.application.services.security_service import SecurityService
from app.domain.exceptions import DomainError

router = Router(name="reviews")


@router.message(Command("review"))
async def review_command(message: Message, repos: dict) -> None:
    if message.chat.type != "private":
        await message.answer("Оставлять отзывы можно в личке бота.")
        return
    args = (message.text or "").split()[1:]
    if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        await message.answer("Формат: /review ID_ВСТРЕЧИ 5 Отличная организация!\nОтзыв можно не писать.")
        return
    event_id, stars = int(args[0]), int(args[1])
    comment = " ".join(args[2:]).strip()
    service = ReviewService(
        repos["reviews"], repos["events"], repos["signups"], repos["event_attendance"]
    )
    try:
        await service.save_review(event_id, message.from_user.id, stars, comment)
        await message.answer("⭐ Оценка и отзыв сохранены. Их можно изменить той же командой.")
    except DomainError as exc:
        await message.answer(exc.message)


@router.message(Command("reviews"))
async def reviews_command(message: Message, repos: dict) -> None:
    args = (message.text or "").split()[1:]
    if len(args) != 1 or not args[0].isdigit():
        await message.answer("Формат: /reviews ID_ВСТРЕЧИ")
        return
    event_id = int(args[0])
    service = ReviewService(
        repos["reviews"], repos["events"], repos["signups"], repos["event_attendance"]
    )
    reviews, count, avg = await service.get_reviews_with_stats(event_id)
    event = await repos["events"].get_by_id(event_id)
    if event is None:
        await message.answer("Встреча не найдена.")
        return
    lines = [
        f"⭐ {event.title}",
        f"Организатор: {event.owner_name or 'Не указан'}",
        f"Средняя оценка: {avg:.1f}/5 ({count} оценок)" if count else "Пока нет оценок",
    ]
    for r in reviews:
        if r.review:
            lines.append(f"{'★' * r.stars} — {r.review[:180]}")
    await message.answer("\n\n".join(lines)[:3900])


@router.message(Command("delreview"))
async def delete_review_command(message: Message, repos: dict) -> None:
    if message.chat.type != "private" or not SecurityService.is_platform_owner(message.from_user.id):
        return
    args = (message.text or "").split()[1:]
    if len(args) != 2 or not all(x.isdigit() for x in args):
        await message.answer("Формат: /delreview ID_ВСТРЕЧИ ID_УЧАСТНИКА")
        return
    event_id, user_id = int(args[0]), int(args[1])
    service = ReviewService(
        repos["reviews"], repos["events"], repos["signups"], repos["event_attendance"]
    )
    deleted = await service.delete_review(event_id, user_id)
    await message.answer("Отзыв удалён." if deleted else "Отзыв не найден.")