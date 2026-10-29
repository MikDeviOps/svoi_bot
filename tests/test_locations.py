"""Тесты normalize_moscow_address."""

from __future__ import annotations

import pytest

from app.services.locations import normalize_moscow_address


@pytest.mark.parametrize("value, expected_city", [
    ("ул. Тверская, 1", "Москва, ул. Тверская, 1"),
    ("  ул. Тверская,  1  ", "Москва, ул. Тверская, 1"),
    ("Москва, Красная площадь", "Москва, Красная площадь"),
    ("мск, Ленинградский пр-т, 5", "мск, Ленинградский пр-т, 5"),
])
def test_normalize_ok(value, expected_city):
    result, error = normalize_moscow_address(value)
    assert error is None
    assert result == expected_city


@pytest.mark.parametrize("value", [
    "Санкт-Петербург, Невский 1",
    "СПб, Лиговский 30",
    "Казань, Баумана 5",
    "Нижний Новгород, ул. Большая Покровская",
])
def test_normalize_other_city(value):
    result, error = normalize_moscow_address(value)
    assert result is None
    assert error is not None
    assert "Москв" in error


def test_normalize_too_short():
    result, error = normalize_moscow_address("abc")
    assert result is None
    assert error is not None


def test_normalize_too_long():
    result, error = normalize_moscow_address("x" * 251)
    assert result is None
    assert error is not None