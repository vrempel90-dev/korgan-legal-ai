from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from korgan.i18n import KK, normalize_language
from korgan.ui import main_menu

LOGGER = logging.getLogger(__name__)
router = Router(name="korgan-claim-route-lock")

_RU_CLAIM_LABELS = {"⚖️ Исковое заявление", "⚖ Исковое заявление", "Исковое заявление"}
_KK_CLAIM_LABELS = {"⚖️ Талап қою арызы", "⚖ Талап қою арызы", "Талап қою арызы"}


async def _enter_claim_waiting(state: FSMContext) -> str:
    data = await state.get_data()
    lang = normalize_language(str(data.get("language", "ru")))
    # Claim selection is a hard document intent.  Never leave a previous
    # consultation mode active, otherwise the next user message can be consumed
    # by the consultation catch-all and returned as plain text instead of DOCX.
    await state.update_data(
        mode="universal_claim_waiting",
        pending_fields=[],
        intake_repeats=0,
        critical_answered=False,
        gate_issues=[],
        claim_draft=None,
    )
    LOGGER.info("KORGAN claim route locked mode=universal_claim_waiting language=%s", lang)
    return lang


def _prompt(lang: str) -> str:
    if lang == KK:
        return (
            "⚖️ Талап қою арызы\n\n"
            "Істің мән-жайын бір хабарламамен жазыңыз. KORGAN фактілер бойынша талаптың нақты түрін анықтап, "
            "ҚР-дың қолданыстағы құқық нормаларын тексеріп, кәсіби рәсімделген Word (.docx) жобасын жасайды."
        )
    return (
        "⚖️ Исковое заявление\n\n"
        "Опишите обстоятельства дела одним сообщением. KORGAN сам определит точный вид иска по фактам, "
        "проверит актуальные нормы права РК и сформирует профессионально оформленный Word (.docx)."
    )


@router.callback_query(F.data == "doc:claim")
async def claim_document_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    lang = await _enter_claim_waiting(state)
    if callback.message is not None:
        await callback.message.answer(_prompt(lang), reply_markup=main_menu(lang))


@router.message(F.text.in_(_RU_CLAIM_LABELS | _KK_CLAIM_LABELS))
async def claim_document_text_button(message: Message, state: FSMContext) -> None:
    lang = await _enter_claim_waiting(state)
    await message.answer(_prompt(lang), reply_markup=main_menu(lang))
