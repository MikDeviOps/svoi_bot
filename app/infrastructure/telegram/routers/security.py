# app/infrastructure/telegram/routers/security.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery

from app.application.services.security_service import SecurityService

router = Router(name="security")


@router.callback_query(F.data == "support:verify")
async def support_verify_callback(query: CallbackQuery, security: SecurityService) -> None:
    is_member = await security.check_support_membership(query.from_user.id)
    if is_member:
        await query.answer("✅ Вы в группе!", show_alert=True)
    else:
        await query.answer("❌ Вы не в группе. Пожалуйста, вступите.", show_alert=True)