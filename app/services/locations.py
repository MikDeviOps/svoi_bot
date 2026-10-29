"""Moscow-first address entry; heuristic, not a geocoder.

Простой фильтр: пропускает «Москва …», добавляет «Москва, » если город не указан,
отвергает явные другие города (СПб, Казань, …).
"""

from __future__ import annotations

import re

OTHER_CITIES = (
    "санкт-петербург", "спб", "казань", "тверь", "нижний новгород",
    "новосибирск", "екатеринбург", "краснодар", "сочи", "воронеж",
    "самара", "тула", "минск", "варшава",
)


def normalize_moscow_address(value: str) -> tuple[str | None, str | None]:
    """Нормализовать адрес для Москвы.

    :return: ``(address, None)`` при успехе, ``(None, error_message)`` при ошибке.
    """
    address = " ".join(value.strip().split())
    if not 5 <= len(address) <= 250:
        return None, "Укажите адрес длиной от 5 до 250 символов."

    lowered = address.casefold().replace("ё", "е")

    for city in OTHER_CITIES:
        if re.search(r"(?<!\w)" + re.escape(city) + r"(?!\w)", lowered):
            return None, (
                "📍 Пока СВОИ работает с мероприятиями в Москве. "
                "Укажите московский адрес или станцию метро."
            )

    if re.search(r"(?<!\w)(москва|мск)(?!\w)", lowered):
        return address, None

    return "Москва, " + address, None