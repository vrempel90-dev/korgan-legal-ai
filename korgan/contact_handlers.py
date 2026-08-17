from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import quote

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from korgan.case_reference import document_label, valid_case_reference
from korgan.i18n import KK, normalize_language
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-contact-handlers")

WHATSAPP_NUMBER_DISPLAY = "+7 700 500 05 53"
WHATSAPP_URL = "https://wa.me/77005000553"


def whatsapp_url_for_case(case_reference: str, document_kind: str, language: str = "ru") -> str:
    """Return a privacy-minimal WhatsApp deep link for one concrete KORGAN case."""
    lang = normalize_language(language)
    label = document_label(document_kind, lang)
    if lang == KK:
        text = (
            f"Сәлеметсіз бе! KORGAN № {case_reference} ісі бойынша хабарласып отырмын. "
            f"Құжат: {label}. Осы іс бойынша жеке заңгердің ақылы консультациясын алғым келеді."
        )
    else:
        text = (
            f"Здравствуйте! Обращаюсь по делу KORGAN № {case_reference}. "
            f"Документ: {label}. Хочу получить платную консультацию персонального юриста по этому делу."
        )
    return f"{WHATSAPP_URL}?text={quote(text)}"


async def _register_lawyer_request(
    state: FSMContext,
    *,
    case_reference: str,
    document_kind: str,
) -> None:
    data = await state.get_data()
    requests = list(data.get("lawyer_requests", []) or [])
    key = (case_reference, document_kind)
    if not any(
        (str(item.get("case_reference", "")), str(item.get("document_kind", ""))) == key
        and str(item.get("status", "")) == "new"
        for item in requests
        if isinstance(item, dict)
    ):
        requests.append({
            "case_reference": case_reference,
            "document_kind": document_kind,
            "status": "new",
            "requested_at": datetime.now(timezone.utc).isoformat(),
        })
    await state.update_data(
        case_reference=case_reference,
        lawyer_requests=requests[-20:],
    )
    LOGGER.info(
        "KORGAN lawyer request registered case_reference=%s document_kind=%s",
        case_reference,
        document_kind,
    )


@router.message(F.text == "👨‍⚖️ Ваш персональный юрист")
async def lawyer_contact(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    lang = normalize_language(str(data.get("language", "ru")))
    case_reference = str(data.get("case_reference", "") or "").strip().upper()
    await state.update_data(mode="main")

    if valid_case_reference(case_reference):
        url = whatsapp_url_for_case(case_reference, "document", lang)
        text = (
            f"👨‍⚖️ Ваш персональный юрист\n\n"
            f"Текущее дело KORGAN: № {case_reference}\n\n"
            "Нажмите кнопку ниже, чтобы открыть WhatsApp. Номер дела уже будет добавлен в сообщение юристу.\n\n"
            f"📱 {WHATSAPP_NUMBER_DISPLAY}"
        )
    else:
        url = WHATSAPP_URL
        text = (
            "👨‍⚖️ Ваш персональный юрист\n\n"
            "Если вам нужна консультация живого юриста, свяжитесь с нами напрямую в WhatsApp.\n\n"
            f"📱 {WHATSAPP_NUMBER_DISPLAY}\n\n"
            "Консультация персонального юриста — платная. Стоимость и условия уточняются до начала работы."
        )

    await message.answer(
        text,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💬 Открыть WhatsApp", url=url)]]
        ),
    )


@router.callback_query(F.data.startswith("lawyer:request:"))
async def lawyer_consultation_requested(callback: CallbackQuery, state: FSMContext) -> None:
    data = str(callback.data or "")
    parts = data.split(":", 3)
    if len(parts) != 4:
        await callback.answer("Не удалось определить дело", show_alert=True)
        return

    _, _, case_reference, document_kind = parts
    case_reference = case_reference.strip().upper()
    if not valid_case_reference(case_reference):
        await callback.answer("Некорректный номер дела", show_alert=True)
        return

    state_data = await state.get_data()
    lang = normalize_language(str(state_data.get("language", "ru")))
    await _register_lawyer_request(
        state,
        case_reference=case_reference,
        document_kind=document_kind,
    )
    url = whatsapp_url_for_case(case_reference, document_kind, lang)
    label = document_label(document_kind, lang)

    await callback.answer("Заявка зарегистрирована" if lang != KK else "Өтінім тіркелді")
    if callback.message is None:
        return

    if lang == KK:
        text = (
            f"✅ KORGAN № {case_reference} ісі бойынша консультацияға өтінім тіркелді.\n"
            f"📄 Құжат: {label}\n\n"
            "WhatsApp-ты ашыңыз — іс нөмірі мен құжат түрі хабарламаға автоматты түрде қосылды. "
            "Хабарламаны жібергеннен кейін заңгер дәл осы істі сәйкестендіре алады."
        )
        button_text = "💬 WhatsApp ашу"
    else:
        text = (
            f"✅ Заявка на консультацию по делу KORGAN № {case_reference} зарегистрирована.\n"
            f"📄 Документ: {label}\n\n"
            "Откройте WhatsApp — номер дела и вид документа уже добавлены в сообщение. "
            "После отправки сообщения юрист сможет сразу определить, по какому делу вы обращаетесь."
        )
        button_text = "💬 Открыть WhatsApp"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=button_text, url=url)]]
        ),
        disable_web_page_preview=True,
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
        "🆘 Техническая поддержка KORGAN\n\n"
        "Если файл не принимается, документ формируется некорректно или возникла техническая ошибка — напишите нам в WhatsApp.\n\n"
        f"📱 {WHATSAPP_NUMBER_DISPLAY}",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="💬 Написать в WhatsApp", url=WHATSAPP_URL)]]
        ),
    )
