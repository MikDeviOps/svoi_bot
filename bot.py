import asyncio
from html import escape
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ConversationHandler,
    MessageHandler, ContextTypes, filters,
)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "")
if not TOKEN or TOKEN == "PASTE_YOUR_TOKEN_HERE":
    raise RuntimeError("Укажите BOT_TOKEN в Replit Secrets или в файле .env")

# Amvera mounts persistent storage at /data. Locally, use the project folder.
DATA_DIR = Path("/data") if Path("/data").is_dir() else Path(__file__).resolve().parent
DB = DATA_DIR / "events.sqlite3"
TZ = ZoneInfo("Europe/Moscow")
TITLE, DESCRIPTION, CATEGORY, DATE, TIME, ADDRESS, CONDITIONS, CAPACITY, VISIBILITY, GROUP = range(10)
EDIT_VALUE = 20
EDIT_FIELDS = {"title": "Название", "description": "Описание", "date": "Дата", "time": "Время", "address": "Адрес", "conditions": "Условия", "capacity": "Количество мест", "category": "Категория"}
DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
CATEGORIES = {
    "games": "🎲 Игры",
    "bars": "🍺 Бары",
    "restaurants": "🍽️ Рестораны",
    "clubs": "💃 Клубы",
    "concerts": "🎤 Концерты",
    "outdoors": "🌳 Пикники и природа",
    "houses": "🏡 Отдых в доме",
    "parties": "🎉 Вечеринки",
    "other": "🎭 Другое",
}
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
EVENT_REFRESH_LOCK = asyncio.Lock()


def connection():
    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    with connection() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            address TEXT NOT NULL,
            conditions TEXT NOT NULL,
            capacity INTEGER NOT NULL CHECK(capacity > 0),
            created_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS signups (
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(event_id, user_id)
        )""")
        # Additive migration: preserve existing signups and meetings while
        # recording a participant's Telegram display name for new signups.
        signup_columns = {
            row["name"] for row in con.execute("PRAGMA table_info(signups)")
        }
        if "telegram_name" not in signup_columns:
            con.execute(
                "ALTER TABLE signups ADD COLUMN telegram_name TEXT NOT NULL DEFAULT ''"
            )
        event_columns = {
            row["name"] for row in con.execute("PRAGMA table_info(events)")
        }
        if "category" not in event_columns:
            con.execute(
                "ALTER TABLE events ADD COLUMN category TEXT NOT NULL DEFAULT 'other'"
            )
        if "source_chat_id" not in event_columns:
            con.execute("ALTER TABLE events ADD COLUMN source_chat_id INTEGER")
        if "visibility" not in event_columns:
            # Existing meetings were globally visible in the imported bot.
            con.execute(
                "ALTER TABLE events ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public'"
            )
        for column, definition in (
            ("description", "TEXT NOT NULL DEFAULT ''"),
            ("owner_name", "TEXT NOT NULL DEFAULT ''"),
            ("source_chat_title", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in event_columns:
                con.execute(f"ALTER TABLE events ADD COLUMN {column} {definition}")
        if "owner_username" not in event_columns:
            con.execute("ALTER TABLE events ADD COLUMN owner_username TEXT NOT NULL DEFAULT ''")
        con.execute("""CREATE TABLE IF NOT EXISTS known_groups (
            chat_id INTEGER PRIMARY KEY, title TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS event_messages (
            event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY(event_id, chat_id, message_id)
        )""")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_agenda "
            "ON events(visibility,source_chat_id,date,category,time)"
        )


def now():
    return datetime.now(TZ)


def event_count(con, event_id):
    return con.execute("SELECT COUNT(*) FROM signups WHERE event_id=?", (event_id,)).fetchone()[0]


def event_card_text(event, private_details=False):
    available = max(0, event["capacity"] - event["booked"])
    category = CATEGORIES.get(event["category"], CATEGORIES["other"])
    lines = [
        f"📍 {event['title']}",
        f"📅 {datetime.fromisoformat(event['date']).strftime('%d.%m.%Y')} · {event['time']} (МСК)",
        f"Категория: {category}",
        f"👥 Участники: {event['booked']}/{event['capacity']} · Свободно: {available}",
    ]
    if event["description"]:
        lines.append(f"📝 Описание: {event['description']}")
    if event["owner_name"]:
        username = event["owner_username"] if "owner_username" in event.keys() else ""
        lines.append(f"👤 Организатор: @{username}" if username else f"👤 Организатор: {event['owner_name']}")
    if event["source_chat_title"]:
        lines.append(f"🏘 Группа: {event['source_chat_title']}")
    if private_details:
        lines.extend((f"🏠 Адрес: {event['address']}", f"📋 Условия: {event['conditions']}"))
    else:
        lines.append("🔒 Точный адрес и условия доступны в личном чате с ботом.")
    return "\n".join(lines)


def event_summary_text(event):
    available = max(0, event["capacity"] - event["booked"])
    category = CATEGORIES.get(event["category"], CATEGORIES["other"])
    return (
        f"📍 {event['title']}\n"
        f"🕒 {event['time']} (МСК) · {category}\n"
        f"👥 {event['booked']}/{event['capacity']} · Свободно: {available}"
    )


def event_keyboard(event, viewer_id=None):
    event_id = event["id"]
    available = event["capacity"] - event["booked"]
    join_label = "Записаться" if available > 0 else "Мест нет"
    join_action = f"join:{event_id}" if available > 0 else f"full:{event_id}"
    rows = [
        [
            InlineKeyboardButton("Подробнее", callback_data=f"detail:{event_id}"),
            InlineKeyboardButton(join_label, callback_data=join_action),
        ],
        [
            InlineKeyboardButton("👥 Участники", callback_data=f"participants:{event_id}"),
            InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel:{event_id}"),
        ],
    ]
    if viewer_id is not None and viewer_id == event["owner_id"]:
        rows.append([InlineKeyboardButton("🗑 Удалить встречу", callback_data=f"deleteask:{event_id}")])
    return InlineKeyboardMarkup(rows)


def event_with_count(con, event_id):
    return con.execute("""SELECT e.*,
            (SELECT COUNT(*) FROM signups s WHERE s.event_id=e.id) AS booked
        FROM events e WHERE e.id=?""", (event_id,)).fetchone()


def scope_key(scope):
    return "public" if scope[0] == "public" else f"chat{scope[1]}"


def scope_from_key(key):
    if key == "public":
        return ("public", None)
    if key.startswith("chat"):
        try:
            return ("chat", int(key[4:]))
        except ValueError:
            return None
    return None


def scope_predicate(scope):
    if scope[0] == "public":
        return "e.visibility='public'", ()
    return "e.visibility='chat' AND e.source_chat_id=?", (scope[1],)


def upcoming_dates(scope):
    predicate, params = scope_predicate(scope)
    today = now().date().isoformat()
    with connection() as con:
        return con.execute(
            f"""SELECT DISTINCT e.date FROM events e
                WHERE {predicate}
                  AND (e.date>? OR (e.date=? AND e.time>?))
                ORDER BY e.date LIMIT 30""",
            (*params, today, today, now().strftime("%H:%M")),
        ).fetchall()


def categories_for_date(scope, d):
    predicate, params = scope_predicate(scope)
    today = now().date().isoformat()
    with connection() as con:
        return con.execute(
            f"""SELECT e.category,COUNT(*) AS event_total FROM events e
                WHERE {predicate} AND e.date=?
                  AND (e.date>? OR (e.date=? AND e.time>?))
                GROUP BY e.category ORDER BY e.category""",
            (*params, d.isoformat(), today, today, now().strftime("%H:%M")),
        ).fetchall()


def events_for_category(scope, d, category, limit=10, offset=0):
    predicate, params = scope_predicate(scope)
    today = now().date().isoformat()
    with connection() as con:
        total = con.execute(
            f"""SELECT COUNT(*) FROM events e
                WHERE {predicate} AND e.date=? AND e.category=?
                  AND (e.date>? OR (e.date=? AND e.time>?))""",
            (*params, d.isoformat(), category, today, today, now().strftime("%H:%M")),
        ).fetchone()[0]
        rows = con.execute(
            f"""SELECT e.*,
                   (SELECT COUNT(*) FROM signups s WHERE s.event_id=e.id) AS booked
                FROM events e
                WHERE {predicate} AND e.date=? AND e.category=?
                  AND (e.date>? OR (e.date=? AND e.time>?))
                ORDER BY e.time,e.id LIMIT ? OFFSET ?""",
            (*params, d.isoformat(), category, today, today, now().strftime("%H:%M"),
             limit, offset),
        ).fetchall()
    return rows, total


async def refresh_event_messages(bot, event_id):
    """Refresh every previously posted card so seat counts stay current."""
    async with EVENT_REFRESH_LOCK:
        with connection() as con:
            event = event_with_count(con, event_id)
            if not event:
                return
            messages = con.execute(
                "SELECT chat_id,message_id FROM event_messages WHERE event_id=?",
                (event_id,),
            ).fetchall()
            keyboard = event_keyboard(event)
        for message in messages:
            try:
                await bot.edit_message_text(
                    chat_id=message["chat_id"],
                    message_id=message["message_id"],
                    text=event_card_text(event, private_details=True),
                    reply_markup=keyboard,
                )
            except TelegramError as exc:
                logger.info(
                    "Could not refresh event card %s in chat %s: %s",
                    event_id, message["chat_id"], exc,
                )


PRIVATE_MENU = ReplyKeyboardMarkup(
    [["📅 Афиша встреч", "➕ Создать встречу"],
     ["📋 Мои встречи", "❓ Помощь"]],
    resize_keyboard=True,
    is_persistent=True,
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = context.args[0] if context.args else ""
    for prefix, handler in (
        ("join_", join_event),
        ("cancel_", cancel_signup),
        ("participants_", show_participants),
        ("detail_", show_event_details),
    ):
        if payload.startswith(prefix):
            try:
                event_id = int(payload[len(prefix):])
            except ValueError:
                await update.message.reply_text("Ссылка на встречу недействительна.")
                return ConversationHandler.END
            if update.effective_chat.type != "private":
                await update.message.reply_text("Откройте ссылку в личном чате с ботом.")
                return ConversationHandler.END
            if handler is show_event_details:
                await handler(update, event_id, context.bot)
            else:
                await handler(update, event_id, context.bot)
            return ConversationHandler.END
    if payload.startswith("create_"):
        try:
            origin_chat_id = int(payload[len("create_"):])
        except ValueError:
            await update.message.reply_text("Ссылка для создания встречи недействительна.")
            return ConversationHandler.END
        if origin_chat_id >= 0:
            await update.message.reply_text("Ссылка не содержит исходный групповой чат.")
            return ConversationHandler.END
        context.user_data["create_origin_chat_id"] = origin_chat_id
        return await create(update, context)
    await update.message.reply_text(
        "Привет! Я СВОИ — афиша встреч Москвы.\n"
        "/vstrechi — афиша встреч\n"
        "/create — создать встречу\n"
        "/mine — мои встречи\n"
        "/help — помощь",
        reply_markup=PRIVATE_MENU if update.effective_chat.type == "private" else None,
    )


async def is_group_admin(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in {"administrator", "creator", "owner"}
    except TelegramError:
        logger.exception("Cannot check administrator status in group %s", chat_id)
        return False


async def begin_event_for_group(update, context, origin_id):
    if not await is_group_admin(context.bot, origin_id, update.effective_user.id):
        await update.effective_message.reply_text("Создавать встречи могут только администраторы выбранной группы.")
        return ConversationHandler.END
    try:
        origin_title = (await context.bot.get_chat(origin_id)).title or "Группа"
    except TelegramError:
        await update.effective_message.reply_text("Не удалось получить название группы. Проверьте, что бот состоит в ней.")
        return ConversationHandler.END
    with connection() as con:
        con.execute("INSERT OR REPLACE INTO known_groups(chat_id,title) VALUES (?,?)", (origin_id, origin_title))
    context.user_data["new_event"] = {
        "source_chat_id": origin_id, "source_chat_title": origin_title,
        "owner_name": update.effective_user.full_name or "Организатор",
        "owner_username": update.effective_user.username or "",
    }
    await update.effective_message.reply_text(f"Группа: {origin_title}\nНазвание встречи? (например: Посиделки в кафе)")
    return TITLE


async def create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if not await is_group_admin(context.bot, update.effective_chat.id, update.effective_user.id):
            await update.message.reply_text("Создавать встречи от группы могут только её администраторы.")
            return ConversationHandler.END
        with connection() as con:
            con.execute("INSERT OR REPLACE INTO known_groups(chat_id,title) VALUES (?,?)", (
                update.effective_chat.id, update.effective_chat.title or "Группа"))
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=create_{update.effective_chat.id}"
        await update.message.reply_text(
            "Группа зарегистрирована. Продолжите создание встречи в личке с ботом:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Открыть личный чат", url=link)
            ]]),
        )
        return ConversationHandler.END
    origin_id = context.user_data.pop("create_origin_chat_id", None)
    if origin_id is not None:
        return await begin_event_for_group(update, context, origin_id)
    with connection() as con:
        groups = con.execute("SELECT chat_id,title FROM known_groups ORDER BY title").fetchall()
    buttons = []
    for group in groups:
        if await is_group_admin(context.bot, group["chat_id"], update.effective_user.id):
            buttons.append([InlineKeyboardButton(
                f"🏠 {group['title'][:45]}", callback_data=f"newgroup:{group['chat_id']}"
            )])
    if not buttons:
        await update.message.reply_text(
            "Пока нет доступных групп. Добавьте бота в свою группу, "
            "отправьте там /create один раз, затем вернитесь в личку."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "Выберите группу, от имени которой создаёте встречу:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return GROUP


async def select_new_group(update, context):
    query = update.callback_query
    await query.answer()
    try:
        origin_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.message.reply_text("Неверная группа.")
        return ConversationHandler.END
    with connection() as con:
        known = con.execute("SELECT 1 FROM known_groups WHERE chat_id=?", (origin_id,)).fetchone()
    if not known:
        await query.message.reply_text("Группа не найдена. Начните заново: /create")
        return ConversationHandler.END
    return await begin_event_for_group(update, context, origin_id)


async def get_title(update, context):
    value = update.message.text.strip()
    if not 3 <= len(value) <= 100:
        await update.message.reply_text("Название должно быть от 3 до 100 символов.")
        return TITLE
    context.user_data["new_event"]["title"] = value
    await update.message.reply_text("Введите описание встречи (или отправьте '-' без описания):")
    return DESCRIPTION


async def get_description(update, context):
    value = update.message.text.strip()
    if len(value) > 1000:
        await update.message.reply_text("Описание не должно превышать 1000 символов.")
        return DESCRIPTION
    context.user_data["new_event"]["description"] = "" if value == "-" else value
    await update.message.reply_text(
        "Выберите категорию встречи:",
        reply_markup=category_selection_keyboard(),
    )
    return CATEGORY


def category_selection_keyboard():
    rows = []
    category_items = list(CATEGORIES.items())
    for start in range(0, len(category_items), 2):
        rows.append([
            InlineKeyboardButton(label, callback_data=f"newcat:{slug}")
            for slug, label in category_items[start:start + 2]
        ])
    return InlineKeyboardMarkup(rows)


async def select_new_category(update, context):
    query = update.callback_query
    await query.answer()
    category = query.data.removeprefix("newcat:")
    if category not in CATEGORIES:
        await query.message.reply_text("Такой категории нет. Выберите категорию ещё раз.")
        return CATEGORY
    context.user_data["new_event"]["category"] = category
    await query.message.reply_text(
        "Дата встречи в формате ДД.ММ.ГГГГ (например, 26.10.2026):"
    )
    return DATE


async def get_date(update, context):
    try:
        d = datetime.strptime(update.message.text.strip(), "%d.%m.%Y").date()
        if d < now().date() or d > (now() + timedelta(days=365)).date():
            raise ValueError
    except ValueError:
        await update.message.reply_text("Укажите будущую дату в формате ДД.ММ.ГГГГ (в пределах года).")
        return DATE
    context.user_data["new_event"]["date"] = d.isoformat()
    await update.message.reply_text("Время по Москве, ЧЧ:ММ (например, 19:00):")
    return TIME


async def get_time(update, context):
    try:
        t = datetime.strptime(update.message.text.strip(), "%H:%M").time()
        d = context.user_data["new_event"]["date"]
        if datetime.fromisoformat(f"{d}T{t.strftime('%H:%M')}").replace(tzinfo=TZ) <= now():
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введите время ЧЧ:ММ, которое ещё не прошло.")
        return TIME
    context.user_data["new_event"]["time"] = t.strftime("%H:%M")
    await update.message.reply_text("Адрес встречи в Москве (метро, улица, дом):")
    return ADDRESS


async def get_address(update, context):
    value = update.message.text.strip()
    if not 5 <= len(value) <= 250:
        await update.message.reply_text("Укажите адрес длиной от 5 до 250 символов.")
        return ADDRESS
    context.user_data["new_event"]["address"] = value
    await update.message.reply_text("Условия встречи (например: депозит 500 ₽ переводом организатору):")
    return CONDITIONS


async def get_conditions(update, context):
    value = update.message.text.strip()
    if not 2 <= len(value) <= 500:
        await update.message.reply_text("Условия должны быть от 2 до 500 символов.")
        return CONDITIONS
    context.user_data["new_event"]["conditions"] = value
    await update.message.reply_text("Максимальное количество участников (от 1 до 1000):")
    return CAPACITY


async def get_capacity(update, context):
    try:
        cap = int(update.message.text.strip())
        if not 1 <= cap <= 1000:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введите число от 1 до 1000.")
        return CAPACITY
    context.user_data["new_event"]["capacity"] = cap
    origin_chat_id = context.user_data["new_event"].get("source_chat_id")
    visibility_buttons = []
    if origin_chat_id is not None:
        visibility_buttons.append([
            InlineKeyboardButton(
                "🏠 Для нашего чата",
                callback_data="newvisibility:chat",
            )
        ])
    visibility_buttons.append([
        InlineKeyboardButton(
            "🌍 Для всех",
            callback_data="newvisibility:public",
        )
    ])
    await update.message.reply_text(
        "Кому будет видна встреча?",
        reply_markup=InlineKeyboardMarkup(visibility_buttons),
    )
    return VISIBILITY


async def select_new_visibility(update, context):
    query = update.callback_query
    await query.answer()
    visibility = query.data.removeprefix("newvisibility:")
    e = context.user_data.get("new_event")
    if not e or visibility not in {"chat", "public"}:
        await query.message.reply_text("Не удалось сохранить выбор. Начните создание встречи заново: /create")
        return ConversationHandler.END
    if e.get("source_chat_id") is None:
        await query.message.reply_text(
            "Сначала выберите группу командой /create."
        )
        return VISIBILITY
    with connection() as con:
        cur = con.execute("""INSERT INTO events
            (owner_id,title,date,time,address,conditions,capacity,created_at,
             category,source_chat_id,visibility,description,owner_name,source_chat_title,owner_username)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                update.effective_user.id, e["title"], e["date"], e["time"],
                e["address"], e["conditions"], e["capacity"], now().isoformat(),
                e["category"], e.get("source_chat_id"),
                visibility if e.get("source_chat_id") is not None else "public",
                e.get("description", ""), e.get("owner_name", ""),
                e.get("source_chat_title", ""), e.get("owner_username", ""),
            ))
        event_id = cur.lastrowid
    context.user_data.pop("new_event", None)
    await query.message.reply_text(
        f"Готово! Встреча №{event_id} добавлена. "
        f"Категория: {CATEGORIES[e['category']]}. "
        f"Видимость: {'только участникам своего чата' if visibility == 'chat' else 'всем пользователям «СВОИ» в Москве'}.\n"
        "/vstrechi — открыть афишу."
    )
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.pop("new_event", None)
    await update.message.reply_text("Создание отменено.")
    return ConversationHandler.END


async def show_scope_menu(message, forced_date=None):
    date_token = forced_date.isoformat() if forced_date else "-"
    buttons = []
    if message.chat.type in {"group", "supergroup"}:
        buttons.append([InlineKeyboardButton(
            "🏠 Встречи нашего чата",
            callback_data=f"scope:chat:{message.chat.id}:{date_token}",
        )])
    buttons.append([InlineKeyboardButton(
        "🌍 Все встречи Москвы",
        callback_data=f"scope:public:{date_token}",
    )])
    await message.reply_text(
        "Выберите афишу:" if forced_date is None else "Выберите афишу на сегодня:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_dates(message, scope):
    dates = upcoming_dates(scope)
    if not dates:
        await message.reply_text(
            "Ближайших встреч в этой афише пока нет.",
        )
        return
    token = scope_key(scope)
    buttons = []
    for row_start in range(0, len(dates), 2):
        row = []
        for item in dates[row_start:row_start + 2]:
            d = datetime.fromisoformat(item["date"]).date()
            row.append(InlineKeyboardButton(
                d.strftime("%d.%m.%Y"),
                callback_data=f"pickdate:{token}:{d.isoformat()}",
            ))
        buttons.append(row)
    await message.reply_text(
        "Ближайшие даты с запланированными встречами:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_categories(message, scope, d):
    categories = categories_for_date(scope, d)
    if not categories:
        await message.reply_text(
            "На эту дату встреч больше нет.",
        )
        return
    token = scope_key(scope)
    rows = []
    items = [
        (row["category"], row["event_total"])
        for row in categories
        if row["category"] in CATEGORIES
    ]
    for start in range(0, len(items), 2):
        rows.append([
            InlineKeyboardButton(
                f"{CATEGORIES[slug]} ({count})",
                callback_data=f"category:{token}:{d.isoformat()}:{slug}:0",
            )
            for slug, count in items[start:start + 2]
        ])
    await message.reply_text(
        f"Выберите категорию · {d.strftime('%d.%m.%Y')}:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def show_event_page(message, scope, d, category, page, bot):
    if category not in CATEGORIES or page < 0:
        await message.reply_text("Не удалось открыть эту страницу.")
        return
    rows, total = events_for_category(scope, d, category, limit=10, offset=page * 10)
    if not rows:
        await message.reply_text(
            "В этой категории на выбранную дату встреч больше нет.",
        )
        return
    for event in rows:
        sent = await message.reply_text(
            event_card_text(event, private_details=True),
            reply_markup=event_keyboard(event),
        )
        with connection() as con:
            con.execute(
                """INSERT OR IGNORE INTO event_messages(event_id,chat_id,message_id)
                   VALUES (?,?,?)""",
                (event["id"], sent.chat_id, sent.message_id),
            )
        await refresh_event_messages(bot, event["id"])

    token = scope_key(scope)
    nav_rows = []
    page_buttons = []
    if (page + 1) * 10 < total:
        page_buttons.append(InlineKeyboardButton(
            "Далее",
            callback_data=f"page:{token}:{d.isoformat()}:{category}:{page + 1}",
        ))
    if page_buttons:
        nav_rows.append(page_buttons)
    if nav_rows:
        await message.reply_text(
            f"Ещё встречи · {CATEGORIES[category]} · страница {page + 1} из {(total + 9) // 10}:",
            reply_markup=InlineKeyboardMarkup(nav_rows),
        )


async def vstrechi(update, context):
    await show_scope_menu(update.effective_message)


async def today(update, context):
    await show_scope_menu(update.effective_message, forced_date=now().date())


async def help_command(update, context):
    await update.effective_message.reply_text(
        "Я помогаю найти и создать встречи в Москве.\n"
        "/vstrechi — открыть афишу\n"
        "/today — встречи на сегодня\n"
        "/create — создать встречу\n"
        "/mine — мои встречи\n"
        "/help — эта справка\n\n"
        "В группе также можно написать отдельным сообщением: «встречи», "
        "«ближайшие встречи», «создать встречу» или «помощь»."
    )


async def text_trigger(update, context):
    if not update.effective_message or not update.effective_message.text:
        return
    value = " ".join(update.effective_message.text.casefold().split())
    if value in {"встречи", "ближайшие встречи", "📅 афиша встреч"}:
        await vstrechi(update, context)
    elif value == "создать встречу":
        if update.effective_chat.type != "private":
            await create(update, context)
    elif value in {"📋 мои встречи"}:
        if update.effective_chat.type == "private":
            await mine(update, context)
    elif value in {"помощь", "❓ помощь"}:
        await help_command(update, context)


async def send_private_link(message, bot, event_id, action, explanation):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={action}_{event_id}"
    await message.reply_text(
        explanation,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Открыть личный чат", url=link)
        ]]),
    )


async def is_source_chat_member(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    except TelegramError as exc:
        logger.info("Could not verify membership in chat %s: %s", chat_id, exc)
        return False
    status = getattr(member.status, "value", member.status)
    return status in {"creator", "administrator", "member"} or (
        status == "restricted" and bool(getattr(member, "is_member", False))
    )


async def can_access_event(update, event, bot):
    if event["visibility"] != "chat":
        return True
    source_chat_id = event["source_chat_id"]
    if source_chat_id is None:
        return False
    chat = update.effective_chat
    if (
        chat
        and chat.type in {"group", "supergroup"}
        and chat.id == source_chat_id
    ):
        return True
    return await is_source_chat_member(
        bot, source_chat_id, update.effective_user.id
    )


def event_visible_in_current_group(event, message):
    if event["visibility"] == "public":
        return True
    # In a private chat the specific handler performs a membership check
    # before showing details, participants, or allowing a new signup.
    if message.chat.type == "private":
        return True
    return (
        message.chat.type in {"group", "supergroup"}
        and event["source_chat_id"] == message.chat.id
    )


async def show_event_details(update, event_id, bot):
    with connection() as con:
        event = event_with_count(con, event_id)
    if not event:
        await update.effective_message.reply_text("Встреча не найдена.")
        return
    if not await can_access_event(update, event, bot):
        await update.effective_message.reply_text(
            "Эта встреча доступна только участникам чата-организатора."
        )
        return
    await update.effective_message.reply_text(
        event_card_text(event, private_details=True),
        reply_markup=event_keyboard(event, update.effective_user.id),
    )


async def join_event(update, event_id, bot):
    user_id = update.effective_user.id
    user = update.effective_user
    with connection() as con:
        access_event = event_with_count(con, event_id)
    if not access_event:
        await update.effective_message.reply_text("Встреча не найдена.")
        return
    if not await can_access_event(update, access_event, bot):
        await update.effective_message.reply_text(
            "Записаться можно только участникам чата-организатора."
        )
        return
    telegram_name = (
        f"@{user.username}" if user.username else (user.full_name or "Имя не указано")
    )
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        e = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        changed = False
        if not e:
            result = "Встреча не найдена."
        elif datetime.fromisoformat(f"{e['date']}T{e['time']}").replace(tzinfo=TZ) <= now():
            result = "Встреча уже началась или прошла."
        elif con.execute("SELECT 1 FROM signups WHERE event_id=? AND user_id=?", (event_id, user_id)).fetchone():
            available = max(0, e["capacity"] - event_count(con, event_id))
            result = f"Вы уже записаны на эту встречу. Свободно мест: {available}."
        elif event_count(con, event_id) >= e["capacity"]:
            result = "К сожалению, свободных мест уже нет. Свободно мест: 0."
        else:
            con.execute(
                """INSERT INTO signups(event_id,user_id,created_at,telegram_name)
                   VALUES (?,?,?,?)""",
                (event_id, user_id, now().isoformat(), telegram_name[:129]),
            )
            available = max(0, e["capacity"] - event_count(con, event_id))
            result = (
                f"Вы записаны на встречу «{e['title']}»!\n"
                f"{e['date']} в {e['time']}\nАдрес: {e['address']}\n"
                f"Условия: {e['conditions']}\nСвободно мест: {available}.\n\n"
                "⚠️ Бот не проверяет оплату. Если указан депозит, "
                "свяжитесь с организатором самостоятельно."
            )
            changed = True
    if changed:
        await refresh_event_messages(bot, event_id)
        mention = f'<a href="tg://user?id={user_id}">{escape(user.full_name or str(user_id))}</a>'
        result = (f'✅ {mention} присоединился(ась) к встрече «{escape(e["title"])}».\n'
                  f'👥 Свободно мест: {available}.')
        await update.effective_message.reply_text(result, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(result)


async def cancel_signup(update, event_id, bot):
    user_id = update.effective_user.id
    user = update.effective_user
    with connection() as con:
        con.execute("BEGIN IMMEDIATE")
        e = con.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        changed = False
        if not e:
            result = "Встреча не найдена."
        elif not con.execute(
            "SELECT 1 FROM signups WHERE event_id=? AND user_id=?",
            (event_id, user_id),
        ).fetchone():
            result = "Вы не записаны на эту встречу."
        else:
            con.execute(
                "DELETE FROM signups WHERE event_id=? AND user_id=?",
                (event_id, user_id),
            )
            available = max(0, e["capacity"] - event_count(con, event_id))
            result = (
                f"Запись на встречу «{e['title']}» отменена. "
                f"Свободно мест: {available}."
            )
            changed = True
    if changed:
        await refresh_event_messages(bot, event_id)
        mention = f'<a href="tg://user?id={user_id}">{escape(user.full_name or str(user_id))}</a>'
        result = (f'❌ {mention} отменил(а) запись на встречу «{escape(e["title"])}».\n'
                  f'👥 Свободно мест: {available}.')
        await update.effective_message.reply_text(result, parse_mode="HTML")
    else:
        await update.effective_message.reply_text(result)


async def show_participants(update, event_id, bot):
    with connection() as con:
        event = event_with_count(con, event_id)
        if not event:
            await update.effective_message.reply_text("Встреча не найдена.")
            return
        rows = con.execute(
            "SELECT telegram_name FROM signups WHERE event_id=? ORDER BY created_at,user_id",
            (event_id,),
        ).fetchall()

    if (
        event["visibility"] == "chat"
        and not await can_access_event(update, event, bot)
    ):
        await update.effective_message.reply_text(
            "Список доступен только участникам чата-организатора."
        )
        return
    count = len(rows)
    heading = (
        f"👥 Участники встречи «{event['title']}»\n"
        f"Записано: {count}/{event['capacity']}"
    )
    names = [
        (row["telegram_name"] or "Имя не указано").replace("\r", " ").replace("\n", " ")
        for row in rows
    ]
    if not names:
        await update.effective_message.reply_text(f"{heading}\nПока никто не записался.")
        return

    chunks = []
    current = heading
    for name in names:
        line = f"\n• {name}"
        if len(current) + len(line) > 3800:
            chunks.append(current)
            current = "👥 Участники (продолжение)"
        current += line
    chunks.append(current)
    for chunk in chunks:
        await update.effective_message.reply_text(chunk)


async def manage_participants(update, context, event_id):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("Управление участниками доступно только в личке.")
        return
    with connection() as con:
        event = event_with_count(con, event_id)
        if not event or event["owner_id"] != update.effective_user.id:
            await update.effective_message.reply_text("Встреча не найдена или вы не организатор.")
            return
        people = con.execute("SELECT user_id,telegram_name FROM signups WHERE event_id=? ORDER BY created_at,user_id", (event_id,)).fetchall()
    if not people:
        await update.effective_message.reply_text("Пока никто не записался.")
        return
    keyboard = [[InlineKeyboardButton("❌ " + (r["telegram_name"] or str(r["user_id"]))[:45], callback_data=f"kickask:{event_id}:{r['user_id']}")] for r in people]
    await update.effective_message.reply_text("Кого удалить из встречи?", reply_markup=InlineKeyboardMarkup(keyboard))


async def start_edit(update, context):
    q = update.callback_query
    await q.answer()
    if q.message.chat.type != "private":
        await q.message.reply_text("Редактирование доступно только в личке с ботом.")
        return ConversationHandler.END
    try:
        event_id = int(q.data.split(":")[1])
        field = q.data.split(":")[2]
    except (IndexError, ValueError):
        return ConversationHandler.END
    if field not in EDIT_FIELDS:
        return ConversationHandler.END
    with connection() as con:
        event = event_with_count(con, event_id)
    if not event or event["owner_id"] != q.from_user.id:
        await q.message.reply_text("Вы не можете редактировать эту встречу.")
        return ConversationHandler.END
    context.user_data["edit_event"] = (event_id, field)
    if field == "category":
        keyboard = [[InlineKeyboardButton(name, callback_data=f"editcat:{event_id}:{key}")] for key, name in CATEGORIES.items()]
        await q.message.reply_text("Выберите категорию:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END
    hints = {"date": "ДД.ММ.ГГГГ", "time": "ЧЧ:ММ (Москва)", "capacity": "число от 1 до 1000"}
    await q.message.reply_text(f"Введите новое значение: {EDIT_FIELDS[field]} ({hints.get(field, 'текст')}).\n/cancel — отмена")
    return EDIT_VALUE


async def receive_edit(update, context):
    state = context.user_data.get("edit_event")
    if not state:
        return ConversationHandler.END
    event_id, field = state
    value = update.message.text.strip()
    try:
        with connection() as con:
            event = event_with_count(con, event_id)
            if not event or event["owner_id"] != update.effective_user.id:
                raise ValueError("Встреча не найдена.")
            if field == "date":
                d = datetime.strptime(value, "%d.%m.%Y").date()
                if not now().date() <= d <= (now() + timedelta(days=365)).date():
                    raise ValueError("Дата должна быть в пределах следующего года.")
                value = d.isoformat()
            elif field == "time":
                value = datetime.strptime(value, "%H:%M").strftime("%H:%M")
            elif field == "capacity":
                value = int(value)
                if not event["booked"] <= value <= 1000 or value < 1:
                    raise ValueError(f"Мест должно быть не меньше числа записанных ({event['booked']}) и не больше 1000.")
            else:
                limits = {"title": (3, 100), "description": (0, 1000), "address": (5, 250), "conditions": (2, 500)}
                low, high = limits[field]
                if not low <= len(value) <= high:
                    raise ValueError(f"Длина текста: от {low} до {high} символов.")
            date = value if field == "date" else event["date"]
            time = value if field == "time" else event["time"]
            if datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=TZ) <= now():
                raise ValueError("Встреча должна быть в будущем.")
            con.execute(f"UPDATE events SET {field}=? WHERE id=? AND owner_id=?", (value, event_id, update.effective_user.id))
    except (ValueError, KeyError) as exc:
        await update.message.reply_text(f"❗ {exc} Попробуйте ещё раз или /cancel.")
        return EDIT_VALUE
    context.user_data.pop("edit_event", None)
    await refresh_event_messages(context.bot, event_id)
    await update.message.reply_text("✅ Встреча обновлена. Карточки в чатах тоже обновлены.")
    return ConversationHandler.END


async def cancel_edit(update, context):
    context.user_data.pop("edit_event", None)
    await update.message.reply_text("Редактирование отменено.")
    return ConversationHandler.END


async def buttons(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    message = q.message
    parts = data.split(":")

    if parts[0] in {"managepeople", "kickask", "kickconfirm", "kickcancel", "editmenu", "editcat"}:
        if message.chat.type != "private":
            await message.reply_text("Управление встречей доступно только в личке с ботом.")
            return
        try:
            event_id = int(parts[1])
        except (IndexError, ValueError):
            await message.reply_text("Неверный номер встречи.")
            return
        with connection() as con:
            event = event_with_count(con, event_id)
        if not event or event["owner_id"] != update.effective_user.id:
            await message.reply_text("Вы не организатор этой встречи или встреча удалена.")
            return
        if parts[0] == "managepeople":
            await manage_participants(update, context, event_id)
        elif parts[0] == "editmenu":
            keyboard = [[InlineKeyboardButton(label, callback_data=f"editfield:{event_id}:{field}")] for field, label in EDIT_FIELDS.items()]
            await message.reply_text("Что изменить?", reply_markup=InlineKeyboardMarkup(keyboard))
        elif parts[0] == "editcat":
            if len(parts) < 3 or parts[2] not in CATEGORIES:
                return
            with connection() as con:
                con.execute("UPDATE events SET category=? WHERE id=? AND owner_id=?", (parts[2], event_id, update.effective_user.id))
            await refresh_event_messages(context.bot, event_id)
            await message.reply_text("✅ Категория изменена.")
        else:
            try:
                user_id = int(parts[2])
            except (IndexError, ValueError):
                return
            with connection() as con:
                person = con.execute("SELECT telegram_name FROM signups WHERE event_id=? AND user_id=?", (event_id, user_id)).fetchone()
            if not person:
                await message.reply_text("Участник уже не записан.")
                return
            name = person["telegram_name"] or str(user_id)
            if parts[0] == "kickask":
                await message.reply_text(f"Удалить участника {name}?", reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Да, удалить", callback_data=f"kickconfirm:{event_id}:{user_id}"),
                    InlineKeyboardButton("Нет", callback_data=f"kickcancel:{event_id}:{user_id}")]]))
            elif parts[0] == "kickcancel":
                await message.reply_text("Удаление отменено.")
            else:
                with connection() as con:
                    deleted = con.execute("DELETE FROM signups WHERE event_id=? AND user_id=?", (event_id, user_id)).rowcount
                if deleted:
                    await refresh_event_messages(context.bot, event_id)
                    await message.reply_text(f"✅ {name} удалён из встречи. Место освобождено.")
                else:
                    await message.reply_text("Участник уже удалён.")
        return

    if parts[0] in {"deleteask", "deleteconfirm", "deletecancel"}:
        if message.chat.type != "private":
            await message.reply_text("Удалять встречи можно только в личке с ботом.")
            return
        try:
            event_id = int(parts[1])
        except (ValueError, IndexError):
            await message.reply_text("Неверный номер встречи.")
            return
        with connection() as con:
            event = event_with_count(con, event_id)
        if not event:
            await message.reply_text("Встреча уже удалена или не найдена.")
            return
        if event["owner_id"] != update.effective_user.id:
            await message.reply_text("Удалить встречу может только её создатель.")
            return
        if parts[0] == "deletecancel":
            await message.reply_text("Удаление отменено.")
        elif parts[0] == "deleteask":
            await message.reply_text(
                f"Удалить встречу «{event['title']}»? Записи участников тоже будут удалены.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Да, удалить", callback_data=f"deleteconfirm:{event_id}"),
                    InlineKeyboardButton("Нет", callback_data=f"deletecancel:{event_id}"),
                ]]),
            )
        else:
            with connection() as con:
                con.execute("BEGIN IMMEDIATE")
                targets = con.execute("SELECT chat_id,message_id FROM event_messages WHERE event_id=?", (event_id,)).fetchall()
                deleted = con.execute("DELETE FROM events WHERE id=? AND owner_id=?", (event_id, update.effective_user.id)).rowcount
            if deleted:
                for target in targets:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=target["chat_id"], message_id=target["message_id"],
                            text="🗑 Эта встреча отменена организатором.",
                            reply_markup=None,
                        )
                    except TelegramError:
                        logger.warning("Could not update deleted event message %s", target["message_id"])
                await message.reply_text("Встреча удалена.")
            else:
                await message.reply_text("Встреча уже удалена.")
        return

    if data == "scope-menu":
        await show_scope_menu(message)
        return

    if parts[0] == "scope":
        try:
            kind = parts[1]
            if kind == "chat":
                if len(parts) != 4:
                    raise ValueError
                source_id = int(parts[2])
                date_token = parts[3]
                scope = ("chat", source_id)
            elif kind == "public":
                if len(parts) != 3:
                    raise ValueError
                date_token = parts[2]
                scope = ("public", None)
            else:
                raise ValueError
        except (ValueError, IndexError):
            await message.reply_text("Не удалось открыть выбранную афишу.")
            return
        if kind == "chat" and (
            message.chat.type not in {"group", "supergroup"}
            or message.chat.id != source_id
        ):
            await message.reply_text(
                "Афиша этого чата открывается только в самом групповом чате."
            )
            return
        if date_token != "-":
            try:
                d = datetime.fromisoformat(date_token).date()
            except ValueError:
                await message.reply_text("Не удалось определить дату.")
                return
            await show_categories(message, scope, d)
        else:
            await show_dates(message, scope)
        return

    if data.startswith("dates:"):
        try:
            scope = scope_from_key(parts[1])
        except IndexError:
            scope = None
        if not scope or (scope[0] == "chat" and (
            message.chat.type not in {"group", "supergroup"}
            or message.chat.id != scope[1]
        )):
            await message.reply_text("Эта афиша доступна только в исходном групповом чате.")
            return
        await show_dates(message, scope)
        return

    if data.startswith("pickdate:"):
        try:
            scope = scope_from_key(parts[1])
            d = datetime.fromisoformat(parts[2]).date()
        except (ValueError, IndexError):
            scope = None
        if not scope or (scope[0] == "chat" and (
            message.chat.type not in {"group", "supergroup"}
            or message.chat.id != scope[1]
        )):
            await message.reply_text("Эта афиша доступна только в исходном групповом чате.")
            return
        await show_categories(message, scope, d)
        return

    if data.startswith("categories:"):
        try:
            scope = scope_from_key(parts[1])
            d = datetime.fromisoformat(parts[2]).date()
        except (ValueError, IndexError):
            scope = None
        if not scope or (scope[0] == "chat" and (
            message.chat.type not in {"group", "supergroup"}
            or message.chat.id != scope[1]
        )):
            await message.reply_text("Эта афиша доступна только в исходном групповом чате.")
            return
        await show_categories(message, scope, d)
        return

    if parts[0] in {"category", "page"}:
        try:
            scope = scope_from_key(parts[1])
            d = datetime.fromisoformat(parts[2]).date()
            category = parts[3]
            page = int(parts[4])
        except (ValueError, IndexError):
            scope = None
        if not scope or (scope[0] == "chat" and (
            message.chat.type not in {"group", "supergroup"}
            or message.chat.id != scope[1]
        )):
            await message.reply_text("Эта афиша доступна только в исходном групповом чате.")
            return
        await show_event_page(message, scope, d, category, page, context.bot)
        return

    if data in {"today"}:
        await show_scope_menu(message, forced_date=now().date())
        return
    if data.startswith("day:"):
        try:
            weekday = int(parts[1])
            if not 0 <= weekday < 7:
                raise ValueError
        except (ValueError, IndexError):
            await message.reply_text("Не удалось определить день недели.")
            return
        d = now().date() + timedelta(days=(weekday - now().weekday()) % 7)
        scope = (
            ("chat", message.chat.id)
            if message.chat.type in {"group", "supergroup"}
            else ("public", None)
        )
        await show_categories(message, scope, d)
        return

    if parts[0] in {"join", "full", "cancel", "participants", "detail"}:
        try:
            event_id = int(parts[1])
        except (ValueError, IndexError):
            await message.reply_text("Неверная встреча.")
            return
        with connection() as con:
            event = event_with_count(con, event_id)
        if not event:
            await message.reply_text("Встреча не найдена.")
            return
        if not event_visible_in_current_group(event, message):
            await message.reply_text(
                "Эта встреча доступна только участникам чата-организатора."
            )
            return
        if parts[0] == "full":
            await message.reply_text("На эту встречу уже нет свободных мест.")
        elif parts[0] == "join":
            await join_event(update, event_id, context.bot)
        elif parts[0] == "cancel":
            await cancel_signup(update, event_id, context.bot)
        elif parts[0] == "participants":
            await show_participants(update, event_id, context.bot)
        else:
            await show_event_details(update, event_id, context.bot)
        return

async def mine(update, context):
    if update.effective_chat.type != "private":
        await update.message.reply_text("Команда /mine доступна в личном чате с ботом.")
        return
    with connection() as con:
        rows = con.execute("""SELECT e.*, (SELECT COUNT(*) FROM signups WHERE event_id=e.id) AS booked
            FROM events e WHERE owner_id=? AND date>=? ORDER BY date,time LIMIT 30""", (update.effective_user.id, now().date().isoformat())).fetchall()
    if not rows:
        await update.message.reply_text("У вас пока нет предстоящих встреч. /create")
        return
    await update.message.reply_text("Ваши встречи:")
    for e in rows:
        await update.message.reply_text(
            f"№{e['id']} · {e['title']} · {e['date']} {e['time']} · {e['booked']}/{e['capacity']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Редактировать", callback_data=f"editmenu:{e['id']}")],
                [InlineKeyboardButton("👥 Управлять участниками", callback_data=f"managepeople:{e['id']}")],
                [InlineKeyboardButton("🗑 Удалить встречу", callback_data=f"deleteask:{e['id']}")],
            ]),
        )


async def configure_bot_menu(application):
    await application.bot.set_my_commands([
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("vstrechi", "Открыть афишу встреч"),
        BotCommand("today", "Показать встречи на сегодня"),
        BotCommand("create", "Создать встречу"),
        BotCommand("mine", "Показать мои встречи"),
        BotCommand("cancel", "Отменить создание встречи"),
        BotCommand("help", "Помощь"),
    ])


def main():
    init_db()
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(configure_bot_menu)
        .build()
    )
    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("create", create),
            MessageHandler(filters.Regex(r"^➕ Создать встречу$") & filters.ChatType.PRIVATE, create),
            CommandHandler("start", start),
        ],
        states={
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_description)],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_title)],
            CATEGORY: [CallbackQueryHandler(select_new_category, pattern=r"^newcat:")],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_date)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_time)],
            ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_address)],
            CONDITIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_conditions)],
            CAPACITY: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_capacity)],
            VISIBILITY: [CallbackQueryHandler(select_new_visibility, pattern=r"^newvisibility:")],
            GROUP: [CallbackQueryHandler(select_new_group, pattern=r"^newgroup:")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],
    )
    app.add_handler(conversation)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_edit, pattern=r"^editfield:\d+:[a-z]+$")],
        states={EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, receive_edit)]},
        fallbacks=[CommandHandler("cancel", cancel_edit)],
        allow_reentry=True,
    ))
    app.add_handler(CommandHandler("vstrechi", vstrechi))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("mine", mine))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_trigger))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
