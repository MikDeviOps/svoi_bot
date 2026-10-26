async def _show_event_page(
    query: CallbackQuery,
    session: AsyncSession,
    scope: tuple[str, int | None],
    day: date,
    category: str,
    page_num: int,
    state: FSMContext,
) -> None:
    from app.routers.events import send_event_card
    from app.services.notifications import CATEGORY_LABELS

    # 1. Удалить старые сообщения афиши (scope, категории, карточки)
    await _delete_agenda_messages(query.message, state)

    # 2. Удалить сообщение категории (на котором кнопки)
    try:
        await query.message.delete()
    except Exception:
        pass

    # 3. Отправить карточки
    service = AgendaService(session)
    events = await service.page(scope, day, category, page=page_num, per_page=10)

    if not events:
        sent = await query.message.answer("В этой категории встреч больше нет.")
        await _track(state, sent.message_id)
        return

    for event in events:
        sent = await send_event_card(
            query.message, session, event, private_details=True, viewer_id=None,
        )
        await _track(state, sent.message_id)

    # 4. Пагинация
    token = _scope_token(scope)
    has_next = len(events) == 10
    kb = pagination_kb(token, day.isoformat(), category, page_num, has_next)
    if kb is not None:
        sent_pag = await query.message.answer(
            f"Ещё · {CATEGORY_LABELS.get(category, category)} · стр. {page_num + 1}:",
            reply_markup=kb,
        )
        await _track(state, sent_pag.message_id)