"""AgendaService — даты, категории, страницы афиши.

scope = ("public", None) | ("chat", chat_id).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import Event
from app.schemas import CATEGORIES, CategoryPage, DatePage


def _predicate(scope: tuple[str, int | None]):
    if scope[0] == "public":
        return Event.visibility == "public", ()
    if scope[0] == "chat":
        return (Event.visibility == "chat") & (Event.source_chat_id == scope[1]), ()
    raise ValueError(f"Unknown scope: {scope!r}")


class AgendaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _now(self) -> datetime:
        return datetime.now(get_settings().timezone)

    async def dates(self, scope: tuple[str, int | None], limit: int = 30) -> DatePage:
        cond, _ = _predicate(scope)
        now = self._now()
        result = await self.session.execute(
            select(func.date_trunc("day", Event.starts_at).label("day"))
            .where(
                cond,
                Event.deleted_at.is_(None),
                Event.starts_at > now,
            )
            .group_by("day")
            .order_by("day")
            .limit(limit)
        )
        return DatePage(dates=[row.day.date() for row in result.all()])

    async def categories(
        self, scope: tuple[str, int | None], day: date
    ) -> CategoryPage:
        cond, _ = _predicate(scope)
        now = self._now()
        start = datetime.combine(day, datetime.min.time()).replace(
            tzinfo=get_settings().timezone
        )
        end = datetime.combine(day, datetime.max.time()).replace(
            tzinfo=get_settings().timezone
        )
        result = await self.session.execute(
            select(Event.category, func.count().label("cnt"))
            .where(
                cond,
                Event.deleted_at.is_(None),
                Event.starts_at >= start,
                Event.starts_at <= end,
                Event.starts_at > now,
            )
            .group_by(Event.category)
        )
        counts: dict[str, int] = {}
        for row in result.all():
            if row.category in CATEGORIES:
                counts[row.category] = int(row.cnt)
        return CategoryPage(date=day, categories=counts)

    async def page(
        self,
        scope: tuple[str, int | None],
        day: date,
        category: str,
        page: int = 0,
        per_page: int = 10,
    ) -> list[Event]:
        cond, _ = _predicate(scope)
        now = self._now()
        start = datetime.combine(day, datetime.min.time()).replace(
            tzinfo=get_settings().timezone
        )
        end = datetime.combine(day, datetime.max.time()).replace(
            tzinfo=get_settings().timezone
        )
        result = await self.session.execute(
            select(Event)
            .where(
                cond,
                Event.deleted_at.is_(None),
                Event.category == category,
                Event.starts_at >= start,
                Event.starts_at <= end,
                Event.starts_at > now,
            )
            .order_by(Event.starts_at, Event.id)
            .offset(page * per_page)
            .limit(per_page)
        )
        return list(result.scalars().all())