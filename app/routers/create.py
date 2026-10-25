async def start_create_from_group(
    message: Message,
    chat_id: int,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Точка входа из deep-link ``create_<chat_id>`` (уже в личке).

    :param message: сообщение от пользователя (в личке).
    :param chat_id: ID группы из deep-link.
    :param session: сессия БД (передаётся из ``start.py``).
    :param state: FSM-контекст.
    """
    await state.update_data(source_chat_id=chat_id)
    await state.set_state(CreateEvent.title)
    await message.answer("Название встречи? (от 3 до 100 символов, например: Посиделки в кафе)")