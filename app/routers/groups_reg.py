"""Роутер для регистрации групп (FSM)."""
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import re

from app.states import GroupReg
from app.db.models import GroupApplication, KnownGroup
from app.config import settings
from app.services.support import has_support_membership, subscription_prompt
from app.utils.time import now_msk

router = Router(name="groups_reg")

@router.message(Command("applygroup", "registergroup", "request"))
@router.message(CommandStart(deep_link=True))
async def cmd_apply_group(message: Message, state: FSMContext, session: AsyncSession):
    """Начало регистрации группы."""
    if message.chat.type != "private":
        await message.answer("Регистрация группы доступна только в личном чате с ботом.")
        return

    # Проверка подписки на поддерживающий чат
    if not await has_support_membership(message.bot, message.from_user.id):
        await message.answer(
            "🔒 Для регистрации группы необходимо вступить в главную группу СВОИ.",
            reply_markup=subscription_prompt()
        )
        return

    # Парсинг deep link: /start apply_-1001234567890
    text = message.text or ""
    match = re.search(r"apply_(-?\d+)", text)
    chat_id = int(match.group(1)) if match else None

    if chat_id:
        await state.update_data(target_chat_id=chat_id)
        await message.answer(
            f"📝 Вы начали регистрацию группы (ID: `{chat_id}`).\n"
            f"Опишите ваш чат: тематика, количество участников, правила. (До 1000 символов).\n"
            f"Для отмены введите /cancel"
        )
    else:
        await message.answer(
            "📝 Чтобы зарегистрировать группу, используйте команду /applygroup или нажмите кнопку в чате группы.\n"
            f"Опишите ваш чат: тематика, количество участников, правила. (До 1000 символов).\n"
            f"Для отмены введите /cancel"
        )
    
    await state.set_state(GroupReg.description)

@router.message(GroupReg.description)
async def process_group_description(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка описания группы и создание заявки."""
    desc = message.text.strip()
    if len(desc) > 1000:
        await message.answer("❗ Описание слишком длинное (макс. 1000 символов). Попробуйте ещё раз:")
        return

    data = await state.get_data()
    target_chat_id = data.get("target_chat_id")

    # Если chat_id не был передан, попросим указать его или получим из контекста (упрощённо: просим пользователя указать)
    if not target_chat_id:
        await message.answer(
            "Пожалуйста, укажите ID группы или используйте кнопку регистрации прямо из этой группы.\n"
            "Заявка отменена.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Меню", callback_data="menu:home")]])
        )
        await state.clear()
        return

    # Проверка, нет ли уже активной заявки
    stmt = select(GroupApplication).where(
        GroupApplication.chat_id == target_chat_id,
        GroupApplication.status.in_(["pending", "approved"])
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        status_text = "уже одобрена" if existing.status == "approved" else "уже находится на рассмотрении"
        await message.answer(f"⚠️ Заявка для этой группы {status_text}.")
        await state.clear()
        return

    # Создаём новую заявку
    new_app = GroupApplication(
        chat_id=target_chat_id,
        title=f"Группа {target_chat_id}", # Будет обновлено при добавлении бота или вручную
        applicant_id=message.from_user.id,
        applicant_name=message.from_user.full_name or "Участник",
        member_count=0, # Будет уточнено
        description=desc,
        status="pending",
        requested_at=now_msk()
    )
    session.add(new_app)
    await state.clear()

    await message.answer(
        "✅ Ваша заявка на регистрацию группы успешно отправлена!\n"
        "Владелец бота рассмотрит её в ближайшее время. Вы получите уведомление о решении."
    )

    # Уведомление владельцев (опционально, можно вынести в фон)
    # for owner_id in settings.owners:
    #     await message.bot.send_message(owner_id, f"📋 Новая заявка на регистрацию группы: {target_chat_id}")

@router.message(Command("cancel"))
async def cmd_cancel_reg(message: Message, state: FSMContext):
    """Отмена регистрации группы."""
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("❌ Регистрация группы отменена.")