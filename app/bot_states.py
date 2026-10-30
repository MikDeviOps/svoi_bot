"""FSM-состояния для сценариев создания и редактирования встречи."""

from aiogram.fsm.state import State, StatesGroup


class CreateEvent(StatesGroup):
    """Шаги создания встречи: group → title → ... → photo → save."""
    group = State()
    title = State()
    description = State()
    category = State()
    date = State()
    time = State()
    address = State()
    conditions = State()
    capacity = State()
    visibility = State()
    photo = State()


class EditEvent(StatesGroup):
    """Шаги редактирования: выбор поля → ввод значения."""
    field_value = State()