# app/presentation/texts.py
from __future__ import annotations

from datetime import datetime
from html import escape

from app.domain.models import Event, Signup, EventExclusion


CATEGORIES: dict[str, str] = {
    "other": "Другое",
    "sport": "Спорт",
    "culture": "Культура",
    "education": "Обучение",
    "networking": "Нетворкинг",
    "games": "Игры",
    "charity": "Благотворительность",
}


def event_card_text(event: Event, booked: int, *, private_details: bool) -> str:
    available = max(0, event.capacity - booked)
    category = CATEGORIES.get(event.category, CATEGORIES["other"])
    try:
        date_str = datetime.fromisoformat(event.date).strftime("%d.%m.%Y")
    except ValueError:
        date_str = event.date

    lines = [
        f"📍 {escape(event.title)}",
        f"📅 {date_str} · {event.time} (МСК)",
        f"Категория: {category}",
        f"👥 Участники: {booked}/{event.capacity} · Свободно: {available}",
    ]
    if event.description:
        lines.append(f"📝 Описание: {escape(event.description)}")
    if event.owner_name:
        if event.owner_username:
            lines.append(f"👤 Организатор: @{escape(event.owner_username.lstrip('@'))}")
        else:
            lines.append(f"👤 Организатор: {escape(event.owner_name)}")
    if event.source_chat_title:
        lines.append(f"🏘 Группа: {escape(event.source_chat_title)}")
    if private_details:
        lines.append(f"🏠 Адрес: {escape(event.address)}")
        lines.append(f"📋 Условия: {escape(event.conditions)}")
    else:
        lines.append("🔒 Точный адрес и условия доступны в личном чате с ботом.")
    return "\n".join(lines)


def event_origin_label(event: Event, current_chat_type: str | None, current_chat_id: int | None) -> str:
    source_id = event.source_chat_id
    source_title = (event.source_chat_title or "").strip()
    if current_chat_type in {"group", "supergroup"}:
        if source_id is not None and source_id == current_chat_id:
            return "нашего чата"
        return "другого чата" if source_id is not None else "из общей афиши"
    if source_title:
        return f"чата «{source_title}»"
    return "из общей афиши"


def organizer_label(event: Event) -> str:
    username = (event.owner_username or "").strip()
    name = (event.owner_name or "").strip()
    if username:
        return "@" + escape(username.lstrip("@"))
    return escape(name or "не указан")


def format_join_success(
    event: Event, user_id: int, user_name: str, available: int, origin: str
) -> str:
    mention = f'<a href="tg://user?id={user_id}">{escape(user_name)}</a>'
    return (
        f"✅ {mention} присоединился(ась) к встрече {origin} «{escape(event.title)}».\n"
        f"👤 Организатор: {organizer_label(event)}\n"
        f"👥 Свободно мест: {available}."
    )


def format_cancel_success(
    event: Event, user_id: int, user_name: str, available: int, origin: str
) -> str:
    mention = f'<a href="tg://user?id={user_id}">{escape(user_name)}</a>'
    return (
        f"❌ {mention} отменил(а) запись на встречу {origin} «{escape(event.title)}».\n"
        f"👤 Организатор: {organizer_label(event)}\n"
        f"👥 Свободно мест: {available}."
    )


def format_participants_chunks(
    heading: str, names: list[str], *, chunk_size: int = 3800
) -> list[str]:
    if not names:
        return [f"{heading}\nПока никто не записался."]
    chunks: list[str] = []
    current = heading
    for name in names:
        line = f"\n• {name}"
        if len(current) + len(line) > chunk_size:
            chunks.append(current)
            current = "👥 Участники (продолжение)"
        current += line
    chunks.append(current)
    return chunks


def format_manage_people(
    event: Event,
    active: list[Signup],
    excluded: list[EventExclusion],
    page: int,
    pages: int,
) -> str:
    lines = [
        f"👥 Участники встречи «{escape(event.title)}»",
        f"Записано: {len(active)}/{event.capacity}",
        "",
    ]
    lines += [f"👤 {s.telegram_name or s.user_id}" for s in active[:30]] or ["Пока никто не записался."]
    lines += ["", f"🚫 Исключённые ({len(excluded)}):"]
    lines += [f"🚫 {e.user_id}" for e in excluded[:30]] or ["Нет исключённых."]
    if len(active) > 30 or len(excluded) > 30:
        lines.append("Показаны первые 30 имён в каждом разделе; кнопки доступны по страницам.")
    return "\n".join(lines)


def format_rating_personal(*, created: int, signed: int, attended: int) -> str:
    return (
        "⭐ Активность в СВОИ\n"
        f"Создано встреч: {created}\n"
        f"Текущих записей: {signed}\n"
        f"Подтверждено посещений: {attended}\n\n"
        "Это статистика, не оценка человека. Посещения засчитываются только после подтверждения."
    )


def format_rating_group(*, title: str, created: int, signed: int) -> str:
    return (
        f"🏠 Активность чата «{escape(title)}»\n"
        f"Создано встреч: {created}\n"
        f"Текущих записей: {signed}\n\n"
        "Это статистика активности, а не оценка качества сообщества."
    )


def format_organizers_list(*, total: int) -> str:
    return (
        f"📊 История организаторов\n"
        f"Всего организаторов: {total}\n"
        "Выберите человека:"
    )


def format_organizer_profile(
    *,
    user_id: int,
    name: str,
    username: str,
    total: int,
    upcoming: int,
    signed: int,
) -> str:
    display_name = name or "Организатор"
    mention = f'<a href="tg://user?id={user_id}">{escape(display_name)}</a>'
    handle = f" (@{escape(username.lstrip('@'))})" if username else ""
    return (
        "📊 История организатора\n\n"
        f"👤 {mention}{handle}\n\n"
        f"📅 Всего создано встреч: {total}\n"
        f"🟢 Предстоящих встреч: {upcoming}\n"
        f"🕒 Прошедших по дате: {total - upcoming}\n"
        f"👥 Всего записей на встречи: {signed}"
    )


def format_organizer_people(
    *, owner_id: int, total: int, rows: list[tuple[int, str, str, int]], offset: int
) -> str:
    lines = [f"👥 Список участников организатора\nВсего человек: {total}\n"]
    for i, (uid, name, username, count) in enumerate(rows, start=offset + 1):
        display = escape(name[:70])
        lines.append(f'{i}. <a href="tg://user?id={uid}">{display}</a> — записей: {count}')
    if not rows:
        lines.append("Записей на встречи пока нет.")
    return "\n".join(lines)