from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan.ui import main_menu

router = Router(name="korgan-contact-handlers")

WHATSAPP_NUMBER_DISPLAY = "+7 700 500 05 53"
WHATSAPP_URL = "https://wa.me/77005000553"


@router.message(F.text == "👨‍⚖️ Ваш персональный юрист")
async def lawyer_contact(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(
        "👨‍⚖️ <b>Ваш персональный юрист</b>\n\n"
        "Если вам нужна консультация живого юриста, свяжитесь с нами напрямую в WhatsApp.\n\n"
        f"💬 <a href=\"{WHATSAPP_URL}\">Написать юристу в WhatsApp</a>\n"
        f"📱 {WHATSAPP_NUMBER_DISPLAY}\n\n"
        "💳 <b>Консультация персонального юриста — платная.</b>\n"
        "Стоимость и условия консультации уточняются у юриста перед началом работы.",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "lawyer:decline")
async def lawyer_consultation_declined(callback: CallbackQuery) -> None:
    """Close the one-time CTA without adding another message to the chat."""
    await callback.answer("Хорошо")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.message(F.text == "🆘 Техподдержка")
async def support_contact(message: Message, state: FSMContext) -> None:
    await state.update_data(mode="main")
    await message.answer(
        "🆘 <b>Техническая поддержка KORGAN</b>\n\n"
        "Если файл не принимается, документ формируется некорректно или возникла техническая ошибка — напишите нам в WhatsApp.\n\n"
        f"💬 <a href=\"{WHATSAPP_URL}\">Написать в техподдержку в WhatsApp</a>\n"
        f"📱 {WHATSAPP_NUMBER_DISPLAY}",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=main_menu(),
    )
