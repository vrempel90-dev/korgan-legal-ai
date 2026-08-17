"""Document-specific lawyer consultation CTA for generated KORGAN files."""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from korgan.i18n import KK, normalize_language
from korgan.language_context import current_fsm_state

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-document-consultation-cta")

WHATSAPP_DISPLAY_NUMBER = "+7 700 500 05 53"
WHATSAPP_NUMBER = "77005000553"
_CASE_ID_KEY = "consultation_case_id"
_DOCUMENT_COUNTER_KEY = "consultation_document_counter"
_CASE_ID_RE = re.compile(r"^KRG-[A-F0-9]{6}$")


@dataclass(frozen=True, slots=True)
class ConsultationReference:
    """Safe reference that identifies one generated file inside one KORGAN case."""

    case_id: str
    document_id: str
    document_number: int
    document_label: str


def _new_case_id() -> str:
    return f"KRG-{secrets.token_hex(3).upper()}"


def _document_label(document: Any, language: str = "ru") -> str:
    filename = str(getattr(document, "filename", "") or "").strip().lower()
    kk = normalize_language(language) == KK
    labels = (
        (("iskovoe_zayavlenie", "claim"), "Талап қою арызы" if kk else "Исковое заявление"),
        (("dosudebnaya_pretenziya", "pretrial", "sotqa_deyingi_talap"), "Сотқа дейінгі талап" if kk else "Досудебная претензия"),
        (("otzyv_na_isk", "response_to_claim"), "Талапқа пікір" if kk else "Отзыв на иск"),
        (("dogovor", "contract"), "Шарт" if kk else "Договор"),
        (("zhaloba", "complaint"), "Шағым" if kk else "Жалоба"),
        (("hodataystvo", "motion"), "Өтінішхат" if kk else "Ходатайство"),
        (("zayavlenie", "application"), "Өтініш" if kk else "Заявление"),
    )
    for markers, label in labels:
        if any(marker in filename for marker in markers):
            return label
    return "Заң құжаты" if kk else "Юридический документ"


async def build_consultation_reference(document: Any, language: str = "ru") -> ConsultationReference:
    """Create a per-document reference while keeping one case id for the FSM case.

    The reference contains no Telegram id, names, IIN/BIN, addresses, case facts
    or document text. Clearing the KORGAN case clears these FSM keys as well, so
    the next generated file starts a new case reference automatically.
    """
    state = current_fsm_state()
    case_id = ""
    document_number = 1

    if state is not None:
        data = await state.get_data()
        stored_case_id = str(data.get(_CASE_ID_KEY, "") or "").strip().upper()
        case_id = stored_case_id if _CASE_ID_RE.fullmatch(stored_case_id) else _new_case_id()
        try:
            previous_number = int(data.get(_DOCUMENT_COUNTER_KEY, 0) or 0)
        except (TypeError, ValueError):
            previous_number = 0
        document_number = max(0, previous_number) + 1
        await state.update_data(
            **{
                _CASE_ID_KEY: case_id,
                _DOCUMENT_COUNTER_KEY: document_number,
            }
        )
    else:
        # Transport calls outside a Telegram FSM still get a non-identifying,
        # unique reference rather than leaking chat/user identifiers.
        case_id = _new_case_id()

    return ConsultationReference(
        case_id=case_id,
        document_id=f"{case_id}-D{document_number:02d}",
        document_number=document_number,
        document_label=_document_label(document, language),
    )


def _whatsapp_text(language: str, reference: ConsultationReference | None) -> str:
    lang = normalize_language(language)
    if reference is None:
        if lang == KK:
            return "Сәлеметсіз бе! KORGAN Legal AI арқылы дайындалған құжат бойынша заңгер кеңесін алғым келеді."
        return "Здравствуйте! Хочу получить консультацию юриста по документу, подготовленному в KORGAN Legal AI."

    if lang == KK:
        return (
            "Сәлеметсіз бе! KORGAN Legal AI арқылы дайындалған нақты құжат бойынша кеңес алғым келеді.\n\n"
            f"Өтініш: {reference.case_id}\n"
            f"Құжат: {reference.document_id} — {reference.document_label}\n\n"
            "Осы құжатты және ол дайындалған жағдайларды талқылағым келеді."
        )
    return (
        "Здравствуйте! Хочу получить консультацию по конкретному документу, подготовленному в KORGAN Legal AI.\n\n"
        f"Обращение: {reference.case_id}\n"
        f"Документ: {reference.document_id} — {reference.document_label}\n\n"
        "Хочу обсудить именно этот документ и обстоятельства, на основании которых он подготовлен."
    )


def whatsapp_url(language: str = "ru", reference: ConsultationReference | None = None) -> str:
    text = _whatsapp_text(language, reference)
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(text, safe='')}"


def consultation_text(language: str = "ru", reference: ConsultationReference | None = None) -> str:
    lang = normalize_language(language)
    if reference is None:
        if lang == KK:
            return "👨‍⚖️ Осы құжат бойынша заңгер кеңесін алғыңыз келе ме?"
        return "👨‍⚖️ Хотите получить консультацию юриста по этому документу?"

    if lang == KK:
        return (
            "👨‍⚖️ Осы нақты құжат бойынша заңгер кеңесі\n\n"
            f"{reference.document_label} · {reference.document_id}\n"
            f"Өтініш: {reference.case_id}\n\n"
            "Заңгер дәл осы құжатты және осы өтініштің мән-жайларын тексереді."
        )
    return (
        "👨‍⚖️ Консультация по конкретному документу\n\n"
        f"{reference.document_label} · {reference.document_id}\n"
        f"Обращение: {reference.case_id}\n\n"
        "Юрист проверит именно этот документ и обстоятельства данного обращения."
    )


def consultation_keyboard(
    language: str = "ru",
    reference: ConsultationReference | None = None,
) -> InlineKeyboardMarkup:
    lang = normalize_language(language)
    if lang == KK:
        yes, no = "💬 Осы құжат бойынша кеңес", "Қазір емес"
    else:
        yes, no = "💬 Консультация по этому документу", "Не сейчас"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=yes, url=whatsapp_url(lang, reference))],
            [InlineKeyboardButton(text=no, callback_data="consultation:no")],
        ]
    )


def is_generated_document(document: Any) -> bool:
    """Only KORGAN-generated court/client artifacts trigger the CTA."""
    if not isinstance(document, BufferedInputFile):
        return False
    filename = str(getattr(document, "filename", "") or "").strip().lower()
    return filename.startswith("korgan_") and filename.endswith((".docx", ".pdf"))


async def send_consultation_cta(
    bot: Bot,
    chat_id: Any,
    language: str = "ru",
    *,
    document: Any | None = None,
) -> Any:
    """Send one CTA tied to the file that was just delivered."""
    lang = normalize_language(language)
    reference = await build_consultation_reference(document, lang) if document is not None else None
    return await Bot.send_message(
        bot,
        chat_id,
        consultation_text(lang, reference),
        reply_markup=consultation_keyboard(lang, reference),
        disable_web_page_preview=True,
    )


def install_compact_document_followup() -> None:
    """Keep internal filing actions but suppress the old long post-claim checklist.

    The court-ready gate still calculates and uses filing actions for release
    decisions. Client UX after a successfully delivered KORGAN file is one
    document-specific lawyer CTA, regardless of document type.
    """
    from korgan import court_ready_claim_guard

    if getattr(court_ready_claim_guard, "_compact_followup_installed", False):
        return

    async def _no_client_checklist(message: Any, state: Any, draft: Any) -> None:
        return None

    court_ready_claim_guard._send_filing_checklist = _no_client_checklist
    court_ready_claim_guard._compact_followup_installed = True
    LOGGER.info("Installed KORGAN document-specific consultation followup")


@router.callback_query(F.data == "consultation:no")
async def consultation_no(callback: CallbackQuery, state: FSMContext) -> None:
    lang = normalize_language(str((await state.get_data()).get("language", "ru")))
    await callback.answer("Жақсы" if lang == KK else "Хорошо")
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
