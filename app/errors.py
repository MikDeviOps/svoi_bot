"""Доменные исключения.

Все ошибки бизнес-логики — наследники ``DomainError``. Каждое несёт
``user_message`` — безопасный для показа пользователю текст. Технические
детали (стек, SQL) — только в логах, не в ``user_message``.

Никаких импортов из ``app.*`` (только stdlib) — чтобы ``routers`` могли
ловить, а ``services`` — кидать, без циклических зависимостей.
"""

from __future__ import annotations


class DomainError(Exception):
    """Базовое доменное исключение.

    :param user_message: текст для пользователя (без технических деталей).
    """

    default_user_message = "Что-то пошло не так. Попробуйте позже."

    def __init__(self, user_message: str | None = None) -> None:
        self.user_message = user_message or self.default_user_message
        super().__init__(self.user_message)

    def __str__(self) -> str:  # для логов
        return f"{type(self).__name__}: {self.user_message}"


class NotFound(DomainError):
    """Сущность не найдена."""

    default_user_message = "Не найдено."


class Forbidden(DomainError):
    """Действие запрещено (не владелец, не админ, не член чата)."""

    default_user_message = "Недостаточно прав."


class Conflict(DomainError):
    """Конфликт состояния (уже записан, уже удалён, нельзя понизить capacity ниже booked)."""

    default_user_message = "Действие невозможно в текущем состоянии."


class CapacityFull(Conflict):
    """На встрече нет свободных мест."""

    default_user_message = "К сожалению, свободных мест уже нет."


class PastEvent(Conflict):
    """Встреча уже началась или прошла."""

    default_user_message = "Встреча уже началась или прошла."


class ValidationError(DomainError):
    """Ошибка валидации пользовательского ввода."""

    default_user_message = "Проверьте введённые данные."