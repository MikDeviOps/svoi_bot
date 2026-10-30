# app/application/services/reputation_service.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from app.application.ports.repositories import (
    EventRepository,
    SignupRepository,
    EventAttendanceRepository,
)


ORGANIZERS_PAGE_SIZE = 8
ORGANIZER_PEOPLE_PAGE_SIZE = 15


class ReputationService:
    def __init__(
        self,
        events: EventRepository,
        signups: SignupRepository,
        attendance: EventAttendanceRepository,
    ) -> None:
        self._events = events
        self._signups = signups
        self._attendance = attendance

    async def get_personal_stats(self, user_id: int) -> dict[str, int]:
        created = await self._events.count_by_owner(user_id)
        signed = await self._signups.count_by_user(user_id)
        attended = await self._attendance.count_attended(user_id)
        return {"created": created, "signed": signed, "attended": attended}

    async def get_group_stats(self, source_chat_id: int) -> dict[str, int]:
        created = await self._events.count_by_source_chat(source_chat_id)
        signed = await self._signups.count_by_source_chat(source_chat_id)
        return {"created": created, "signed": signed}

    async def list_organizers(
        self, page: int
    ) -> tuple[int, Sequence[tuple[int, str, str, int]]]:
        total = await self._events.count_organizers()
        offset = max(0, page) * ORGANIZERS_PAGE_SIZE
        rows = await self._events.list_organizers(
            limit=ORGANIZERS_PAGE_SIZE, offset=offset, event_cutoff=0
        )
        return total, rows

    async def get_organizer_profile(
        self, owner_id: int
    ) -> dict | None:
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        clock = now.strftime("%H:%M")
        rows = await self._events.list_organizers(limit=1, offset=0, event_cutoff=0)
        match = next((r for r in rows if r[0] == owner_id), None)
        if match is None:
            return None
        _, name, username, total = match
        upcoming = await self._events.count_upcoming_by_owner(
            owner_id, after_id=0, today=today, clock=clock
        )
        signed = await self._signups.count_by_owner_after_cutoff(owner_id, signup_cutoff=0)
        return {
            "owner_id": owner_id,
            "name": name,
            "username": username,
            "total": total,
            "upcoming": upcoming,
            "signed": signed,
        }

    async def get_organizer_people(
        self, owner_id: int, page: int
    ) -> tuple[int, Sequence[tuple[int, str, str, int]]]:
        total = await self._signups.count_people_by_owner(owner_id)
        offset = max(0, page) * ORGANIZER_PEOPLE_PAGE_SIZE
        rows = await self._signups.list_people_by_owner(
            owner_id, limit=ORGANIZER_PEOPLE_PAGE_SIZE, offset=offset
        )
        return total, rows