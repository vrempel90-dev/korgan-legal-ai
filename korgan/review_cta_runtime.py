from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from korgan.i18n import KK
from korgan.language_context import current_language

router = Router(name="korgan-review-cta")


@router.callback_query(F.data == "lawyer_review:claim:no")
async def decline_claim_review(callback: CallbackQuery) -> None:
    """Dismiss the optional paid lawyer-review offer without touching the case."""
    text = (
        "Түсінікті. Талап қою арызы чатта қалады."
        if current_language() == KK
        else "Хорошо. Иск остаётся у вас в чате."
    )
    await callback.answer(text)
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            # Declining the optional CTA must never affect the legal-document flow.
            pass
