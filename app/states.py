"""FSM состояния для диалогов СВОИ."""
from aiogram.fsm.state import State, StatesGroup

class CreateEvent(StatesGroup):
    title = State()
    description = State()
    category = State()
    date = State()
    time = State()
    address = State()
    conditions = State()
    capacity = State()
    visibility = State()
    group = State()
    photo = State()

class EditEvent(StatesGroup):
    value = State()

class GroupReg(StatesGroup):
    description = State()