from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from korgan.i18n import KK
from korgan.language_context import current_language

router = Router(name="korgan-review-cta")

_DECLINE_CALLBACKS = {
    "lawyer_review:claim:no": "claim",
    "lawyer_review:pretrial:no": "pretrial",
    "lawyer_review:response:no": "response",
    "lawyer_review:contract:no": "contract",
}


def _decline_text(kind: str, language: str) -> str:
    if language == KK:
        return {
            "claim": "Түсінікті. Талап қою арызы чатта қалады.",
            "pretrial": "Түсінікті. Сотқа дейінгі талап чатта қалады.",
            "response": "Түсінікті. Пікір чатта қалады.",
            "contract": "Түсінікті. Шарт чатта қалады.",
        }[kind]
    return {
        "claim": "Хорошо. Иск остаётся у вас в чате.",
        "pretrial": "Хорошо. Досудебная претензия остаётся у вас в чате.",
        "response": "Хорошо. Отзыв на иск остаётся у вас в чате.",
        "contract": "Хорошо. Договор остаётся у вас в чате.",
    }[kind]


@router.callback_query(F.data.in_(set(_DECLINE_CALLBACKS)))
async def decline_document_review(callback: CallbackQuery) -> None:
    """Dismiss an optional paid lawyer-review offer without touching the case."""
    kind = _DECLINE_CALLBACKS.get(callback.data or "")
    if kind is None:
        return
    await callback.answer(_decline_text(kind, current_language()))
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            # Declining the optional CTA must never affect the legal-document flow.
            pass
