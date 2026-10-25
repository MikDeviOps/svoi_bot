"""FSM-состояния для создания и редактирования встречи."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CreateEvent(StatesGroup):
    """FSM создания: title → description → category → date → time → address → conditions → capacity → visibility → group."""

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


class EditEvent(StatesGroup):
    """FSM редактирования: выбор поля → ввод значения."""

    field_value = State()