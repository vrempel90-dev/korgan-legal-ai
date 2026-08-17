"""One compact lawyer-consultation CTA after every generated KORGAN document."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from korgan.i18n import KK, normalize_language

router = Router(name="korgan-document-consultation-cta")

WHATSAPP_DISPLAY_NUMBER = "+7 700 500 05 53"
WHATSAPP_NUMBER = "77005000553"
_WHATSAPP_TEXT_RU = (
    "Здравствуйте! Я подготовил документ в KORGAN Legal AI и хочу получить консультацию юриста по нему."
)
_WHATSAPP_TEXT_KK = (
    "Сәлеметсіз бе! Мен KORGAN Legal AI арқылы құжат дайындадым және осы құжат бойынша заңгер кеңесін алғым келеді."
)


def whatsapp_url(language: str = "ru") -> str:
    lang = normalize_language(language)
    text = _WHATSAPP_TEXT_KK if lang == KK else _WHATSAPP_TEXT_RU
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(text, safe='')}"


def consultation_text(language: str = "ru") -> str:
    if normalize_language(language) == KK:
        return (
            "👨‍⚖️ Құжатты пайдаланар алдында заңгердің кеңесі қажет. "
            "Заңгер істің мән-жайларын, деректемелерді, талаптар немесе шарттарды және құқық нормаларының нақты жағдайға қолданылуын тексереді.\n\n"
            "Заңгер кеңесін алғыңыз келе ме?"
        )
    return (
        "👨‍⚖️ Перед использованием документа требуется консультация юриста. "
        "Юрист проверит обстоятельства дела, реквизиты, требования или условия документа и применимость норм права именно к вашей ситуации.\n\n"
        "Хотите получить консультацию?"
    )


def consultation_keyboard(language: str = "ru") -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    if lang == KK:
        yes, no = "✅ Иә, кеңес алу", "Жоқ, рақмет"
    else:
        yes, no = "✅ Да, получить консультацию", "Нет, спасибо"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=yes, url=whatsapp_url(lang))],
            [InlineKeyboardButton(text=no, callback_data="consultation:no")],
        ]
    )


def is_generated_document(document: Any) -> bool:
    """Only KORGAN-generated court/client artifacts trigger the CTA."""
    if not isinstance(document, BufferedInputFile):
        return False
    filename = str(getattr(document, "filename", "") or "").strip().lower()
    return filename.startswith("korgan_") and filename.endswith((".docx", ".pdf"))


async def send_consultation_cta(bot: Bot, chat_id: Any, language: str = "ru") -> Any:
    """Use Bot.send_message directly so document transport cannot recurse."""
    lang = normalize_language(language)
    return await Bot.send_message(
        bot,
        chat_id,
        consultation_text(lang),
        reply_markup=consultation_keyboard(lang),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "consultation:no")
async def consultation_no(callback: CallbackQuery, state: FSMContext) -> None:
    lang = normalize_language(str((await state.get_data()).get("language", "ru")))
    await callback.answer("Жақсы" if lang == KK else "Хорошо")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
