# app/application/services/event_service.py
from __future__ import annotations

from app.application.ports.repositories import EventRepository, SignupRepository, EventExclusionRepository
from app.domain.exceptions import EventNotFoundError, PermissionDeniedError
from app.domain.models import Event


class EventService:
    def __init__(
        self,
        events: EventRepository,
        signups: SignupRepository,
        exclusions: EventExclusionRepository,
    ) -> None:
        self._events = events
        self._signups = signups
        self._exclusions = exclusions

    async def get_event_with_count(self, event_id: int) -> tuple[Event, int]:
        result = await self._events.get_with_booked_count(event_id)
        if result is None:
            raise EventNotFoundError()
        return result

    async def delete_event(self, event_id: int, user_id: int, *, is_platform_owner: bool) -> bool:
        event = await self._events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError()
        if event.owner_id != user_id and not is_platform_owner:
            raise PermissionDeniedError("Только организатор может удалить встречу.")
        # CASCADE удалит signups, event_messages, event_exclusions, event_attendance, event_reviews
        await self._events.delete(event_id)
        return True