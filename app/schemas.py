"""Pydantic-схемы: черновик FSM, view-модели, результаты сервисов."""

from __future__ import annotations          # ← ВАЖНО: отложенные аннотации

from datetime import date as dt_date, datetime as dt_datetime, time as dt_time
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

from app.config import get_settings
from app.errors import ValidationError

Visibility = Literal["public", "chat"]

CATEGORIES: tuple[str, ...] = (
    "games", "bars", "restaurants", "clubs", "concerts",
    "outdoors", "houses", "parties", "other",
)
Category = Literal[
    "games", "bars", "restaurants", "clubs", "concerts",
    "outdoors", "houses", "parties", "other",
]


class EventDraft(BaseModel):
    """Черновик встречи, заполняется по шагам в FSM.

    Поля ``event_date``/``event_time`` (а не ``date``/``time``) — чтобы
    не конфликтовать с именами типов из ``datetime``.
    """

    title: str | None = None
    description: str = ""
    category: Category | None = None
    event_date: dt_date | None = None
    event_time: dt_time | None = None
    address: str | None = None
    conditions: str | None = None
    capacity: int | None = None
    visibility: Visibility | None = None
    source_chat_id: int | None = None
    source_chat_title: str = ""
    owner_name: str = ""
    owner_username: str = ""

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is None:
            return v
        s = get_settings()
        v = v.strip()
        if not (s.title_min_len <= len(v) <= s.title_max_len):
            raise ValidationError(
                f"Название должно быть от {s.title_min_len} до {s.title_max_len} символов."
            )
        return v

    @field_validator("description")
    @classmethod
    def _description(cls, v: str) -> str:
        s = get_settings()
        v = v.strip()
        if len(v) > s.description_max_len:
            raise ValidationError(
                f"Описание не должно превышать {s.description_max_len} символов."
            )
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in CATEGORIES:
            raise ValidationError("Такой категории нет.")
        return v

    @field_validator("address")
    @classmethod
    def _address(cls, v: str | None) -> str | None:
        if v is None:
            return v
        s = get_settings()
        v = v.strip()
        if not (s.address_min_len <= len(v) <= s.address_max_len):
            raise ValidationError(
                f"Адрес должен быть от {s.address_min_len} до {s.address_max_len} символов."
            )
        return v

    @field_validator("conditions")
    @classmethod
    def _conditions(cls, v: str | None) -> str | None:
        if v is None:
            return v
        s = get_settings()
        v = v.strip()
        if not (s.conditions_min_len <= len(v) <= s.conditions_max_len):
            raise ValidationError(
                f"Условия должны быть от {s.conditions_min_len} до {s.conditions_max_len} символов."
            )
        return v

    @field_validator("capacity")
    @classmethod
    def _capacity(cls, v: int | None) -> int | None:
        if v is None:
            return v
        s = get_settings()
        if not (s.capacity_min <= v <= s.capacity_max):
            raise ValidationError(
                f"Количество мест должно быть от {s.capacity_min} до {s.capacity_max}."
            )
        return v

    @model_validator(mode="after")
    def _starts_at_in_future(self) -> EventDraft:
        if self.event_date is None or self.event_time is None:
            return self
        s = get_settings()
        starts_at = dt_datetime.combine(self.event_date, self.event_time).replace(
            tzinfo=s.timezone
        )
        if starts_at <= dt_datetime.now(s.timezone):
            raise ValidationError("Встреча должна быть в будущем.")
        if (self.event_date - dt_datetime.now(s.timezone).date()).days > s.event_horizon_days:
            raise ValidationError(
                f"Дата должна быть не позже чем через {s.event_horizon_days} дней."
            )
        return self


class EventView(BaseModel):
    """Готовая к показу встреча (карточка)."""

    id: int
    title: str
    description: str
    category: Category
    starts_at: dt_datetime
    address: str
    conditions: str
    capacity: int
    booked: int
    visibility: Visibility
    source_chat_id: int | None
    source_chat_title: str
    owner_id: int
    owner_display: str

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.booked)


class JoinResult(BaseModel):
    joined: bool
    reason: str = ""
    available: int = 0


class CancelResult(BaseModel):
    cancelled: bool
    reason: str = ""
    available: int = 0


class DatePage(BaseModel):
    dates: list[dt_date]


class CategoryPage(BaseModel):
    date: dt_date
    categories: dict[str, int]