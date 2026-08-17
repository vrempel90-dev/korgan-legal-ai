from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan.claim_intent import is_claim_drafting_request
from korgan.contract_intent import is_contract_drafting_request
from korgan.i18n import KK, normalize_language
from korgan.pretrial import is_pretrial_request
from korgan.response_intent import is_response_to_claim_request
from korgan.ui import documents_menu

DocumentIntent = Literal["claim", "pretrial", "response", "contract"]

router = Router(name="korgan-document-intent-lock")

_SELECTED_MODE: dict[str, DocumentIntent] = {
    "universal_claim_waiting": "claim",
    "pretrial_waiting": "pretrial",
    "response_details": "response",
    "contract_details": "contract",
}

_RU_LABELS: dict[DocumentIntent, str] = {
    "claim": "Исковое заявление",
    "pretrial": "Досудебная претензия",
    "response": "Отзыв на иск",
    "contract": "Договор",
}
_KK_LABELS: dict[DocumentIntent, str] = {
    "claim": "Талап қою арызы",
    "pretrial": "Сотқа дейінгі талап",
    "response": "Талап қою арызына пікір",
    "contract": "Шарт",
}

# The dedicated RU classifiers predate full Kazakh document routing.  Keep the
# language additions here deterministic so a selected document mode cannot
# silently turn a Kazakh drafting command into the wrong document.
_KK_CONTRACT_NOUN = re.compile(r"(?i)\b(?:шарт\w*|келісімшарт\w*|келісім\w*)\b")
_KK_RESPONSE_NOUN = re.compile(
    r"(?i)(?:талап\s+қою\s+арыз\w*.{0,50}(?:пікір\w*|қарсылық\w*)|"
    r"(?:пікір\w*|қарсылық\w*).{0,50}талап\s+қою\s+арыз\w*|"
    r"талап-арыз\w*.{0,50}(?:пікір\w*|қарсылық\w*))"
)
_KK_ACTION = re.compile(r"(?i)\b(?:дайында\w*|жаса\w*|құрастыр\w*|әзірле\w*|жаз\w*|қалыптастыр\w*)\b")
_ADVICE = re.compile(r"(?i)(?:^\s*(?:как|қалай)\b|\bқалай\b.{0,100}(?:дайында|жаса|құрастыр|әзірле))")


def _kk_contract_request(text: str) -> bool:
    return bool(_KK_CONTRACT_NOUN.search(text) and _KK_ACTION.search(text) and not _ADVICE.search(text))


def _kk_response_request(text: str) -> bool:
    return bool(_KK_RESPONSE_NOUN.search(text) and _KK_ACTION.search(text) and not _ADVICE.search(text))


def detect_document_intent(text: str | None) -> DocumentIntent | None:
    """Return one explicit drafting intent; facts/advice intentionally return None.

    Priority matters: «отзыв на иск» is a response, not a claim, and a request for
    a pre-trial demand that merely mentions a future claim is still pre-trial.
    A court claim «по договору займа» remains a claim rather than a contract.
    """
    value = " ".join((text or "").split()).strip()
    if not value:
        return None

    if is_response_to_claim_request(value) or _kk_response_request(value):
        return "response"
    if is_pretrial_request(value):
        return "pretrial"
    if is_claim_drafting_request(value):
        return "claim"
    if is_contract_drafting_request(value) or _kk_contract_request(value):
        return "contract"
    return None


@dataclass(frozen=True, slots=True)
class IntentMismatch:
    selected: DocumentIntent
    requested: DocumentIntent


def selected_intent_mismatch(mode: str | None, text: str | None) -> IntentMismatch | None:
    selected = _SELECTED_MODE.get(str(mode or ""))
    if selected is None:
        return None
    requested = detect_document_intent(text)
    if requested is None or requested == selected:
        return None
    return IntentMismatch(selected=selected, requested=requested)


class IntentMismatchFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool | dict[str, IntentMismatch]:
        if not message.text or message.text.startswith("/"):
            return False
        data = await state.get_data()
        mismatch = selected_intent_mismatch(str(data.get("mode", "")), message.text)
        return {"intent_mismatch": mismatch} if mismatch is not None else False


def _message(mismatch: IntentMismatch, language: str) -> str:
    lang = normalize_language(language)
    if lang == KK:
        labels = _KK_LABELS
        return (
            f"Қазір «{labels[mismatch.selected]}» бөлімі ашық, бірақ хабарламада «{labels[mismatch.requested]}» дайындауды сұрадыңыз. "
            "KORGAN әртүрлі құжат түрлерін араластырмайды. Төмендегі мәзірден қажетті құжат бөлімін таңдаңыз."
        )
    labels = _RU_LABELS
    return (
        f"Сейчас открыт раздел «{labels[mismatch.selected]}», но в сообщении вы просите подготовить «{labels[mismatch.requested]}». "
        "KORGAN не будет смешивать разные виды документов. Выберите нужный раздел ниже и отправьте запрос там."
    )


@router.message(IntentMismatchFilter())
async def document_intent_mismatch(
    message: Message,
    state: FSMContext,
    intent_mismatch: IntentMismatch,
) -> None:
    data = await state.get_data()
    lang = normalize_language(str(data.get("language", "ru")))
    # The mismatching command is deliberately not appended to case facts.  Clear
    # only the active document mode; uploaded documents and facts stay intact.
    await state.update_data(mode="main")
    await message.answer(
        _message(intent_mismatch, lang),
        reply_markup=documents_menu(lang),
    )
