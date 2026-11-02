"""Роутер для создания встречи (FSM, 11 шагов)."""
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.states import CreateEvent
from app.keyboards.common import CATEGORIES, PRIVATE_MENU
from app.config import settings
from app.db.repo.events import create_event
from app.utils.time import now_msk

router = Router(name="creation")


def validate_date(text: str) -> tuple[bool, str]:
    try:
        dt = datetime.strptime(text, "%d.%m.%Y").date()
        now = now_msk()
        if not (now.date() <= dt <= (now + timedelta(days=365)).date()):
            return False, "Дата должна быть в пределах следующего года."
        return True, dt.isoformat()
    except ValueError:
        return False, "Неверный формат. Используйте ДД.ММ.ГГГГ (например, 25.12.2024)."


def validate_time(text: str) -> tuple[bool, str]:
    try:
        return True, datetime.strptime(text, "%H:%M").strftime("%H:%M")
    except ValueError:
        return False, "Неверный формат. Используйте ЧЧ:ММ (например, 18:30)."


@router.message(Command("create"))
@router.message(F.text == "➕ Создать встречу")
async def cmd_create_start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        await message.reply_text("Создание встречи доступно только в личном чате с ботом.")
        return
    await state.set_state(CreateEvent.title)
    await message.answer(
        "➕ <b>Создание новой встречи</b>\n\n"
        "Введите <b>название</b> встречи (от 3 до 100 символов).\n"
        "Для отмены введите /cancel",
    )


@router.message(StateFilter(CreateEvent.title), Command("cancel"))
@router.message(StateFilter(CreateEvent.title), F.text == "❌ Отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание встречи отменено. Главное меню:", reply_markup=PRIVATE_MENU)


@router.message(StateFilter(CreateEvent.title), F.text, ~F.text.startswith("/"))
async def process_title(message: Message, state: FSMContext):
    if len(message.text) < 3 or len(message.text) > 100:
        await message.answer("❗ Название должно быть от 3 до 100 символов. Попробуйте ещё раз:")
        return
    
    await state.update_data(title=message.text.strip())
    await state.set_state(CreateEvent.description)
    await message.answer(
        "📝 Введите <b>описание</b> встречи (до 1000 символов).\n"
        "Можно оставить пустым (отправьте «-» или просто нажмите Enter)."
    )


@router.message(StateFilter(CreateEvent.description), Command("cancel"))
@router.message(StateFilter(CreateEvent.description), F.text == "❌ Отмена")
async def cmd_cancel_desc(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание встречи отменено.", reply_markup=PRIVATE_MENU)


@router.message(StateFilter(CreateEvent.description), F.text, ~F.text.startswith("/"))
async def process_description(message: Message, state: FSMContext):
    desc = message.text.strip()
    if desc == "-":
        desc = ""
    if len(desc) > 1000:
        await message.answer("❗ Описание слишком длинное (макс. 1000 символов). Попробуйте ещё раз:")
        return
    
    await state.update_data(description=desc)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"create_cat:{key}")]
        for key, name in CATEGORIES.items()
    ])
    await state.set_state(CreateEvent.category)
    await message.answer("🏷 Выберите <b>категорию</b> встречи:", reply_markup=kb)


@router.callback_query(F.data.startswith("create_cat:"), StateFilter(CreateEvent.category))
async def process_category(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    category_key = callback.data.split(":")[1]
    if category_key not in CATEGORIES:
        await callback.message.answer("Неверная категория.")
        return
    
    await state.update_data(category=category_key)
    await callback.message.edit_text(f"✅ Категория выбрана: {CATEGORIES[category_key]}\n\nВведите <b>дату</b> встречи (ДД.ММ.ГГГГ):")
    await state.set_state(CreateEvent.date)


@router.message(StateFilter(CreateEvent.date), Command("cancel"))
@router.message(StateFilter(CreateEvent.date), F.text == "❌ Отмена")
async def cmd_cancel_date(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание встречи отменено.", reply_markup=PRIVATE_MENU)


@router.message(StateFilter(CreateEvent.date), F.text, ~F.text.startswith("/"))
async def process_date(message: Message, state: FSMContext):
    is_valid, result = validate_date(message.text.strip())
    if not is_valid:
        await message.answer(f"❗ {result}\nПопробуйте ещё раз:")
        return
    
    await state.update_data(date=result)
    await state.set_state(CreateEvent.time)
    await message.answer("⏰ Введите <b>время</b> встречи в формате ЧЧ:ММ (по Москве):")


@router.message(StateFilter(CreateEvent.time), Command("cancel"))
@router.message(StateFilter(CreateEvent.time), F.text == "❌ Отмена")
async def cmd_cancel_time(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание встречи отменено.", reply_markup=PRIVATE_MENU)


@router.message(StateFilter(CreateEvent.time), F.text, ~F.text.startswith("/"))
async def process_time(message: Message, state: FSMContext):
    is_valid, result = validate_time(message.text.strip())
    if not is_valid:
        await message.answer(f"❗ {result}\nПопробуйте ещё раз:")
        return
    
    await state.update_data(time=result)
    await state.set_state(CreateEvent.address)
    await message.answer("📍 Введите <b>адрес</b> проведения (от 5 до 250 символов):")


@router.message(StateFilter(CreateEvent.address), Command("cancel"))
@router.message(StateFilter(CreateEvent.address), F.text == "❌ Отмена")
async def cmd_cancel_addr(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание встречи отменено.", reply_markup=PRIVATE_MENU)


@router.message(StateFilter(CreateEvent.address), F.text, ~F.text.startswith("/"))
async def process_address(message: Message, state: FSMContext):
    addr = message.text.strip()
    if len(addr) < 5 or len(addr) > 250:
        await message.answer("❗ Адрес должен быть от 5 до 250 символов. Попробуйте ещё раз:")
        return
    
    await state.update_data(address=addr)
    await state.set_state(CreateEvent.conditions)
    await message.answer("⚙️ Введите <b>условия</b> участия (например, 'бесплатно', 'депозит 500р') (от 2 до 500 символов):")


@router.message(StateFilter(CreateEvent.conditions), Command("cancel"))
@router.message(StateFilter(CreateEvent.conditions), F.text == "❌ Отмена")
async def cmd_cancel_cond(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание встречи отменено.", reply_markup=PRIVATE_MENU)


@router.message(StateFilter(CreateEvent.conditions), F.text, ~F.text.startswith("/"))
async def process_conditions(message: Message, state: FSMContext):
    cond = message.text.strip()
    if len(cond) < 2 or len(cond) > 500:
        await message.answer("❗ Условия должны быть от 2 до 500 символов. Попробуйте ещё раз:")
        return
    
    await state.update_data(conditions=cond)
    await state.set_state(CreateEvent.capacity)
    await message.answer("👥 Введите <b>максимальное количество участников</b> (число от 1 до 1000):")


@router.message(StateFilter(CreateEvent.capacity), Command("cancel"))
@router.message(StateFilter(CreateEvent.capacity), F.text == "❌ Отмена")
async def cmd_cancel_cap(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Создание встречи отменено.", reply_markup=PRIVATE_MENU)


@router.message(StateFilter(CreateEvent.capacity), F.text, ~F.text.startswith("/"))
async def process_capacity(message: Message, state: FSMContext):
    try:
        cap = int(message.text.strip())
        if not (1 <= cap <= 1000):
            raise ValueError
    except ValueError:
        await message.answer("❗ Введите корректное число от 1 до 1000:")
        return
    
    await state.update_data(capacity=cap)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Публичная (видна всем в афише)", callback_data="create_vis:public")],
        [InlineKeyboardButton(text="🔒 Только для чата (видна только в чате создания)", callback_data="create_vis:chat")]
    ])
    await state.set_state(CreateEvent.visibility)
    await message.answer("👁 Выберите <b>видимость</b> встречи:", reply_markup=kb)


@router.callback_query(F.data.startswith("create_vis:"), StateFilter(CreateEvent.visibility))
async def process_visibility(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    vis = callback.data.split(":")[1]
    if vis not in ("public", "chat"):
        await callback.message.answer("Неверная видимость.")
        return
    
    await state.update_data(visibility=vis)
    await callback.message.edit_text(
        "Отправьте <b>фото</b> для встречи (или нажмите /skip, чтобы пропустить):"
    )
    await state.set_state(CreateEvent.photo)


@router.message(StateFilter(CreateEvent.photo), Command("skip"))
@router.message(StateFilter(CreateEvent.photo), F.text == "/skip")
async def skip_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    await state.update_data(photo_file_id="")
    await finalize_creation(message, state, session, bot)


@router.message(StateFilter(CreateEvent.photo), F.photo)
async def process_photo(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_file_id=photo_id)
    await finalize_creation(message, state, session, bot)


@router.message(StateFilter(CreateEvent.photo))
async def warn_photo(message: Message):
    await message.answer("⚠️ Пожалуйста, отправьте фотографию или введите /skip для пропуска.")


async def finalize_creation(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    """Сбор данных и сохранение в БД."""
    data = await state.get_data()
    await state.clear()
    
    # Формируем starts_at из date и time
    dt_str = f"{data['date']}T{data['time']}"
    starts_at = datetime.fromisoformat(dt_str).replace(tzinfo=settings.tzinfo)
    
    # Создаём встречу через репозиторий
    new_event = await create_event(
        session=session,
        owner_id=message.from_user.id,
        owner_name=message.from_user.full_name or "Участник",
        owner_username=message.from_user.username or "",
        title=data["title"],
        description=data["description"],
        category=data["category"],
        starts_at=starts_at,
        address=data["address"],
        conditions=data["conditions"],
        capacity=data["capacity"],
        visibility=data["visibility"],
        photo_file_id=data.get("photo_file_id", ""),
        source_chat_id=None,
        source_chat_title=""
    )
    event_id = new_event.id
    
    await message.answer(
        f"✅ Встреча «<b>{data['title']}</b>» успешно создана!\n"
        f"ID встречи: <code>{event_id}</code>\n\n"
        f"Теперь вы можете отправить её в чат или управлять ею через /mine",
        reply_markup=PRIVATE_MENU
    )