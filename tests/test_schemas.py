"""Тесты валидаторов EventDraft. Без БД — чистый pydantic."""

from __future__ import annotations

from datetime import date as dt_date, time as dt_time, timedelta

import pytest

from app.errors import ValidationError
from app.schemas import EventDraft


# --- title ---


def test_title_too_short():
    with pytest.raises(ValidationError, match="Название"):
        EventDraft(title="ab")


def test_title_too_long():
    with pytest.raises(ValidationError, match="Название"):
        EventDraft(title="x" * 101)


def test_title_ok():
    d = EventDraft(title="  Посиделки  ")
    assert d.title == "Посиделки"


# --- description ---


def test_description_too_long():
    with pytest.raises(ValidationError, match="Описание"):
        EventDraft(description="x" * 1001)


def test_description_ok():
    assert EventDraft(description="").description == ""


# --- category ---


def test_category_invalid():
    with pytest.raises(ValidationError, match="категории"):
        EventDraft(category="unknown")


def test_category_ok():
    d = EventDraft(category="games")
    assert d.category == "games"


# --- address ---


def test_address_too_short():
    with pytest.raises(ValidationError, match="Адрес"):
        EventDraft(address="abc")


def test_address_ok():
    d = EventDraft(address="  ул. Тверская, 1  ")
    assert d.address == "ул. Тверская, 1"


# --- conditions ---


def test_conditions_too_short():
    with pytest.raises(ValidationError, match="Условия"):
        EventDraft(conditions="a")


def test_conditions_ok():
    d = EventDraft(conditions="  депозит 500  ")
    assert d.conditions == "депозит 500"


# --- capacity ---


def test_capacity_zero():
    with pytest.raises(ValidationError, match="Количество мест"):
        EventDraft(capacity=0)


def test_capacity_too_high():
    with pytest.raises(ValidationError, match="Количество мест"):
        EventDraft(capacity=1001)


def test_capacity_ok():
    assert EventDraft(capacity=10).capacity == 10


# --- date/time ---


def test_date_time_in_past():
    yesterday = dt_date.today() - timedelta(days=1)
    with pytest.raises(ValidationError, match="в будущем"):
        EventDraft(event_date=yesterday, event_time=dt_time(19, 0))


def test_date_too_far():
    far = dt_date.today() + timedelta(days=400)
    with pytest.raises(ValidationError, match="не позже"):
        EventDraft(event_date=far, event_time=dt_time(19, 0))


def test_date_time_ok():
    tomorrow = dt_date.today() + timedelta(days=1)
    d = EventDraft(event_date=tomorrow, event_time=dt_time(19, 0))
    assert d.event_date == tomorrow and d.event_time == dt_time(19, 0)


# --- visibility ---


def test_visibility_invalid():
    with pytest.raises(Exception):
        EventDraft(visibility="everyone")


def test_visibility_ok():
    assert EventDraft(visibility="public").visibility == "public"
    assert EventDraft(visibility="chat").visibility == "chat"