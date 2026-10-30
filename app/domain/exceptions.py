# app/domain/exceptions.py
from __future__ import annotations


class DomainError(Exception):
    """Базовое доменное исключение. Сообщение — для пользователя."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """Сущность не найдена."""


class EventNotFoundError(NotFoundError):
    def __init__(self) -> None:
        super().__init__("Встреча не найдена.")


class ReviewValidationError(DomainError):
    """Ошибка валидации отзыва."""


class PermissionDeniedError(DomainError):
    """Нет прав на действие."""


class UserBlockedError(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "⛔ Вы заблокированы в СВОИ. Для решения вопроса обратитесь в раздел «❓ Помощь»."
        )


class GroupBlockedError(DomainError):
    def __init__(self) -> None:
        super().__init__("⛔ Эта группа заблокирована на платформе СВОИ.")


class GroupNotApprovedError(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "⏳ Группа пока не одобрена владельцами СВОИ. Для регистрации напишите «Встречи» в группе."
        )


class NotGroupAdminError(DomainError):
    def __init__(self) -> None:
        super().__init__("⛔ Создавать встречи могут только администраторы группы.")


class GroupTooSmallError(DomainError):
    def __init__(self, current: int, minimum: int) -> None:
        super().__init__(
            f"⛔ Для создания встреч требуется минимум {minimum} участников. Сейчас в группе: {current}."
        )


class EventAlreadyStartedError(DomainError):
    def __init__(self) -> None:
        super().__init__("Встреча уже началась или прошла.")


class EventFullError(DomainError):
    def __init__(self) -> None:
        super().__init__("К сожалению, свободных мест уже нет. Свободно мест: 0.")


class AlreadySignedUpError(DomainError):
    def __init__(self, available: int) -> None:
        super().__init__(
            f"Вы уже записаны на эту встречу. Свободно мест: {available}."
        )


class NotSignedUpError(DomainError):
    def __init__(self) -> None:
        super().__init__("Вы не записаны на эту встречу.")


class EventExcludedError(DomainError):
    def __init__(self) -> None:
        super().__init__(
            "⛔ Организатор исключил вас из этой встречи. Повторная запись недоступна."
        )


class AccessDeniedError(DomainError):
    def __init__(self) -> None:
        super().__init__("Эта встреча доступна только участникам чата-организатора.")