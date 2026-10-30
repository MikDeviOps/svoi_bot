# app/application/services/review_service.py
from __future__ import annotations

from datetime import datetime, timezone

from app.application.ports.repositories import ReviewRepository, EventRepository, SignupRepository, EventAttendanceRepository
from app.domain.exceptions import (
    EventNotFoundError,
    ReviewValidationError,
)
from app.domain.models import EventReview


class ReviewService:
    def __init__(
        self,
        reviews: ReviewRepository,
        events: EventRepository,
        signups: SignupRepository,
        attendance: EventAttendanceRepository,
    ) -> None:
        self._reviews = reviews
        self._events = events
        self._signups = signups
        self._attendance = attendance

    async def save_review(
        self,
        event_id: int,
        user_id: int,
        stars: int,
        comment: str,
    ) -> None:
        event = await self._events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError()
        if user_id == event.owner_id:
            raise ReviewValidationError("Нельзя оценивать свою встречу")
        if not 1 <= stars <= 5:
            raise ReviewValidationError("Оценка должна быть от 1 до 5")
        if len(comment) > 600:
            raise ReviewValidationError("Отзыв слишком длинный (максимум 600 символов)")
        try:
            event_dt = datetime.fromisoformat(f"{event.date}T{event.time}").replace(tzinfo=timezone.utc)
            if event_dt >= datetime.now(timezone.utc):
                raise ReviewValidationError("Оценить встречу можно только после её начала")
        except ValueError:
            pass
        registered = await self._signups.get(event_id, user_id)
        confirmed = await self._attendance.get(event_id, user_id)
        if not registered and not (confirmed and confirmed.attended):
            raise ReviewValidationError("Оценивать могут только записанные участники")
        if confirmed and not confirmed.attended:
            raise ReviewValidationError("Нельзя оценивать встречу, если отсутствие подтверждено")
        review = EventReview(
            event_id=event_id,
            user_id=user_id,
            stars=stars,
            review=comment,
            event_title=event.title,
            organizer_id=event.owner_id,
        )
        await self._reviews.save(review)

    async def delete_review(self, event_id: int, user_id: int) -> bool:
        return await self._reviews.delete(event_id, user_id)

    async def get_reviews_with_stats(
        self, event_id: int
    ) -> tuple[list[EventReview], int, float | None]:
        reviews = await self._reviews.list_by_event(event_id, limit=15)
        count, avg = await self._reviews.get_stats(event_id)
        return list(reviews), count, avg